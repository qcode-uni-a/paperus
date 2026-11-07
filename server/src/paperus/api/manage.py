"""What needs looking at: the numbers next to Manage → Duplicates,
Unsorted and Missing in the menu, and Manage → Missing (papers without a
file, or with only their preprint's)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import aliased

from paperus import duplicates, library, missing, system
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
        snapshots=len(_snapshots(db, access)),
    )


# Web pages Zotero saved with a paper ("snapshots"): with a PDF of the same
# version they add nothing but noise in search.
SNAPSHOT_TYPES = ("text/html", "application/xhtml+xml")


def _snapshots(db: DB, access: CurrentAccess) -> list[File]:
    """Saved web pages next to a PDF of the same version, on papers the
    person may change."""
    pdf = aliased(File)
    files = db.scalars(
        select(File)
        .join(Version, Version.id == File.version_id)
        .join(Item, Item.id == Version.item_id)
        .where(
            File.media_type.in_(SNAPSHOT_TYPES),
            File.deleted_at.is_(None),
            Item.deleted_at.is_(None),
            access.item_filter(access.readable),
            select(pdf.id)
            .where(
                pdf.version_id == File.version_id,
                pdf.media_type == PDF,
                pdf.deleted_at.is_(None),
            )
            .exists(),
        )
    )
    return [file for file in files if access.can_write_item(file.version.item)]


class Trashed(BaseModel):
    trashed: int


@router.post("/api/manage/snapshots/trash")
def trash_snapshots(db: DB, access: CurrentAccess) -> Trashed:
    """Move saved web pages that sit next to a PDF to the trash (they can
    be restored from there)."""
    files = _snapshots(db, access)
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
    """Why that try found none."""


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
        raise HTTPException(409, f"no open-access copy found: {item.open_access_error}")
    queue_text_extraction(request.app.state.jobs, file.id)
    return file_out(file)


class Queued(BaseModel):
    papers: int


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
    email = system.load_config(db, request.app.state.settings).contact_email
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
    queued = 0
    for item in candidates:
        if access.can_write_item(item) and _possible(item, section == "journal", email):
            queue_open_access(request.app.state.jobs, item.id, access.user.id, section)
            queued += 1
    return Queued(papers=queued)


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
