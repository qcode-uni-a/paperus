"""What needs looking at: the numbers next to Manage → Duplicates,
Unsorted and Missing in the menu, and Manage → Missing (papers without a
file, or with only their preprint's)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session, aliased

from paperus import duplicates, library, missing, system
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.api.files import PDF, FileOut, file_out, unreadable
from paperus.api.items import ItemOut, get_readable_item, item_out, unsorted_conditions
from paperus.jobs import queue_open_access, queue_text_extraction
from paperus.models import File, Item, Version

router = APIRouter(tags=["manage"])

# "Try all" leaves out papers tried this recently.
RETRY_AFTER = timedelta(days=1)


class ManageCounts(BaseModel):
    duplicates: int
    """Pairs that look like the same paper and are not decided yet."""
    unsorted: int
    """Papers whose details were only guessed from their file."""
    unreadable: int
    """Files whose text could not be read."""
    missing: int = 0
    """Papers without a file (and not marked as needing none)."""
    missing_journal: int = 0
    """Published papers with only their preprint's file."""
    snapshots: int = 0
    """Saved web pages next to a PDF of the same version, which the person
    may remove (see ``POST /api/manage/snapshots/trash``)."""


def _count(db: DB, access: CurrentAccess, *conditions: ColumnElement[bool]) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Item)
            .where(access.item_filter(access.readable), *conditions)
        )
        or 0
    )


@router.get("/api/manage/counts")
def manage_counts(db: DB, access: CurrentAccess) -> ManageCounts:
    """How many duplicates, unsorted papers, unreadable files and papers
    missing a file the person can see."""
    return ManageCounts(
        duplicates=len(duplicates.find(db, access)),
        unsorted=_count(
            db,
            access,
            Item.deleted_at.is_(None),
            Item.archived_at.is_(None),
            *unsorted_conditions(),
        ),
        unreadable=len(unreadable(db, access)),
        missing=_count(db, access, *missing.conditions("file")),
        missing_journal=_count(db, access, *missing.conditions("journal")),
        snapshots=len(web_page_copies(db, access)),
    )


# Web pages Zotero saved with a paper ("snapshots"): with a PDF of the same
# version they add nothing but noise in search.
SNAPSHOT_TYPES = ("text/html", "application/xhtml+xml")


def next_to_a_pdf() -> ColumnElement[bool]:
    """Files other than PDFs with a PDF in the same version."""
    pdf = aliased(File)
    return (File.media_type != PDF) & (
        select(pdf.id)
        .where(
            pdf.version_id == File.version_id,
            pdf.media_type == PDF,
            pdf.deleted_at.is_(None),
        )
        .exists()
    )


def web_page_copies(db: Session, access: Access) -> list[File]:
    """Saved web pages next to a PDF of the same version, on papers the
    person may change."""
    files = db.scalars(
        select(File)
        .join(Version, Version.id == File.version_id)
        .join(Item, Item.id == Version.item_id)
        .where(
            File.media_type.in_(SNAPSHOT_TYPES),
            File.deleted_at.is_(None),
            Item.deleted_at.is_(None),
            access.item_filter(access.readable),
            next_to_a_pdf(),
        )
    )
    return [file for file in files if access.can_write_item(file.version.item)]


class Trashed(BaseModel):
    trashed: int


@router.post("/api/manage/snapshots/trash")
def trash_snapshots(db: DB, access: CurrentAccess) -> Trashed:
    """Move saved web pages that sit next to a PDF to the trash (they can
    be restored from there)."""
    files = web_page_copies(db, access)
    for file in files:
        library.trash(file, access.user.id)
    db.commit()
    return Trashed(trashed=len(files))


class MissingPaper(BaseModel):
    item: ItemOut
    version_id: uuid.UUID | None
    """The version the file is missing for (an upload goes there): the
    published one for papers with only their preprint's file."""
    open_access: bool
    """The server may find an open-access copy: an arXiv ID or a DOI (the
    journal's open copy, the arXiv version, or one Unpaywall knows); for
    the journal's version, its DOI."""
    tried_at: datetime | None
    """The last try to download an open-access copy."""
    error: str | None
    """Why that try found none, as noted (addresses and HTTP errors)."""
    reason: str | None = None
    """The same in plain words, with what to do."""


class MissingCounts(BaseModel):
    file: int
    journal: int


class MissingPapers(BaseModel):
    papers: list[MissingPaper]
    total: int
    counts: MissingCounts
    """Of each section."""
    hidden: int
    """Papers marked as needing no (further) file (``hidden=true``)."""


def _possible(item: Item, journal: bool, email: str | None) -> bool:
    if journal:
        return missing.journal_doi(item) is not None
    return missing.may_have_copy(item, email)


@router.get("/api/manage/missing")
def missing_papers(
    request: Request,
    db: DB,
    access: CurrentAccess,
    section: missing.Section = "file",
    hidden: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MissingPapers:
    """Papers the person can see that miss a file, newest first: without
    any (``section=file``), or published ones with only their preprint's
    (``section=journal``); with ``hidden=true`` those marked as needing no
    (further) file, of both sections."""
    readable = access.item_filter(access.readable)
    email = system.load_config(db, request.app.state.settings).contact_email
    shown = missing.hidden_conditions() if hidden else missing.conditions(section)
    items = db.scalars(
        select(Item)
        .where(readable, *shown)
        .order_by(Item.id.desc())
        .offset(offset)
        .limit(limit)
    ).unique()

    def entry(item: Item) -> MissingPaper:
        has_file = any(f.deleted_at is None for v in item.versions for f in v.files)
        journal = missing.journal_version(item) if has_file else None
        version = journal or library.preferred_version(item)
        return MissingPaper(
            item=item_out(item, access),
            version_id=version.id if version else None,
            open_access=_possible(item, journal is not None, email),
            tried_at=item.open_access_tried_at,
            error=item.open_access_error,
            reason=missing.plain_reason(item.open_access_error, email),
        )

    return MissingPapers(
        papers=[entry(item) for item in items],
        total=_count(db, access, *shown),
        counts=MissingCounts(
            file=_count(db, access, *missing.conditions("file")),
            journal=_count(db, access, *missing.conditions("journal")),
        ),
        hidden=_count(db, access, *missing.hidden_conditions()),
    )


@router.post("/api/items/{item_id}/open-access")
def download_open_access(
    item_id: uuid.UUID,
    request: Request,
    db: DB,
    access: CurrentAccess,
    section: missing.Section = "file",
) -> FileOut:
    """Download an open-access copy of the paper and add it: for a paper
    without a file, from arXiv (also its arXiv version, found by its DOI)
    or one Unpaywall knows; for the journal's version (``section=journal``)
    only the journal's own copy. 409 with the reason if none is found."""
    item = get_readable_item(db, access, item_id)
    access.require_write_item(item)
    settings = request.app.state.settings
    add = missing.add_journal_copy if section == "journal" else missing.add_open_access
    file = add(
        db,
        request.app.state.http,
        request.app.state.blobs,
        item,
        contact_email=system.load_config(db, settings).contact_email,
        max_bytes=system.max_upload_bytes(db, settings),
        user_id=access.user.id,
    )
    if file is None:
        email = system.load_config(db, settings).contact_email
        raise HTTPException(
            409,
            missing.plain_reason(item.open_access_error, email)
            or "No open-access copy found.",
        )
    queue_text_extraction(request.app.state.jobs, file.id)
    return file_out(file)


class Queued(BaseModel):
    papers: int
    item_ids: list[uuid.UUID] = []
    """The papers queued, to follow with ``…/open-access/progress``."""
    started_at: datetime | None = None


@router.post("/api/manage/missing/open-access", status_code=202)
def download_all_open_access(
    request: Request,
    db: DB,
    access: CurrentAccess,
    section: missing.Section = "file",
) -> Queued:
    """Try to download open-access copies for all papers of the section
    that the person may change, in the background (not those tried in the
    last day)."""
    queued, started_at = queue_all_open_access(db, access, request.app.state, section)
    return Queued(papers=len(queued), item_ids=queued, started_at=started_at)


def queue_all_open_access(
    db: Session,
    access: Access,
    state: Any,  # noqa: ANN401 (Starlette's app.state)
    section: missing.Section,
) -> tuple[list[uuid.UUID], datetime]:
    """Queue a download for every paper of the section the person may
    change and that was not tried in the last day; those papers and when."""
    email = system.load_config(db, state.settings).contact_email
    recently = datetime.now(UTC) - RETRY_AFTER
    candidates = db.scalars(
        select(Item).where(
            access.item_filter(access.writable),
            *missing.conditions(section),
            or_(
                Item.open_access_tried_at.is_(None),
                Item.open_access_tried_at < recently,
            ),
        )
    ).unique()
    started_at = datetime.now(UTC)
    queued: list[uuid.UUID] = []
    for item in candidates:
        if access.can_write_item(item) and _possible(item, section == "journal", email):
            queue_open_access(state.jobs, item.id, access.user.id, section)
            queued.append(item.id)
    return queued, started_at


class ProgressRequest(BaseModel):
    item_ids: list[uuid.UUID] = Field(max_length=10_000)
    started_at: datetime
    section: missing.Section = "file"


class NotFound(BaseModel):
    item_id: uuid.UUID
    title: str
    reason: str
    """Why no copy was found, in plain words with what to do."""


class Progress(BaseModel):
    tried: int
    """Of the papers, how many were tried since the start."""
    found: int
    """Of those, how many got their file."""
    not_found: list[NotFound] = []
    """The others: tried, and still without their file."""


@router.post("/api/manage/missing/open-access/progress")
def open_access_progress(
    body: ProgressRequest, request: Request, db: DB, access: CurrentAccess
) -> Progress:
    """How far a "Download all" has got: the papers tried since it started,
    and how many of them have their file now."""
    email = system.load_config(db, request.app.state.settings).contact_email
    return progress_of(db, access, body.item_ids, body.started_at, body.section, email)


def progress_of(
    db: Session,
    access: Access,
    item_ids: list[uuid.UUID],
    started_at: datetime,
    section: missing.Section,
    contact_email: str | None,
) -> Progress:
    """Of these papers: how many were tried since ``started_at``, how many
    of those have their file now, and why the others have not."""
    items = list(
        db.scalars(
            select(Item).where(
                Item.id.in_(item_ids),
                access.item_filter(access.readable),
                Item.open_access_tried_at >= started_at,
            )
        ).unique()
    )
    still_missing = set(
        db.scalars(
            select(Item.id).where(
                Item.id.in_([item.id for item in items]),
                *missing.conditions(section),
            )
        )
    )
    return Progress(
        tried=len(items),
        found=sum(item.id not in still_missing for item in items),
        not_found=[
            NotFound(
                item_id=item.id,
                title=item.title,
                reason=missing.plain_reason(item.open_access_error, contact_email)
                or "No open-access copy found.",
            )
            for item in items
            if item.id in still_missing
        ],
    )


class FileWanted(BaseModel):
    wanted: bool


@router.put("/api/items/{item_id}/file-wanted", status_code=204)
def set_file_wanted(
    item_id: uuid.UUID, body: FileWanted, db: DB, access: CurrentAccess
) -> None:
    """Mark a paper as needing no (further) file: it leaves Manage → Missing;
    or as needing one again."""
    item = get_readable_item(db, access, item_id)
    access.require_write_item(item)
    item.file_wanted = body.wanted
    db.commit()
