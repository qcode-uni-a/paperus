"""Papers without a file (Manage → Missing), and getting them one: an
open-access copy fetched by the server (arXiv, or by DOI via Unpaywall).
A paper known only by its DOI is looked for on arXiv first (OpenAlex);
found, it gets its preprint version from there, with that PDF. Copies
behind a publisher's login come through the person's browser instead (the
browser extension, or an upload)."""

import re
import uuid
from datetime import UTC, datetime
from typing import Literal

import httpx2
from sqlalchemy import ColumnElement, Select, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import library, metadata, open_access
from paperus.identifiers import Scheme, implied_by_doi, is_arxiv_doi, normalize
from paperus.models import (
    Blob,
    File,
    FileRole,
    FileSource,
    Identifier,
    Item,
    MetadataSource,
    Version,
    VersionKind,
)
from paperus.storage import BlobStore, StoredBlob

PDF = "application/pdf"


Section = Literal["file", "journal"]
""""file": papers without any file; "journal": published papers whose
journal version has no file, while their preprint has one."""

JOURNAL = (VersionKind.PUBLISHED, VersionKind.ACCEPTED)


def _with_files() -> Select[uuid.UUID]:
    return select(Version.item_id).join(File).where(File.deleted_at.is_(None))


def _journal_without_file() -> Select[uuid.UUID]:
    return select(Version.item_id).where(
        Version.kind.in_(JOURNAL),
        ~exists().where(File.version_id == Version.id, File.deleted_at.is_(None)),
    )


def conditions(
    section: Section = "file", *, wanted: bool = True
) -> list[ColumnElement[bool]]:
    """Papers (not in the trash or the archive) missing a file of the section's kind;
    ``wanted=False``: those marked as needing no (further) file instead."""
    found = [
        Item.deleted_at.is_(None),
        Item.archived_at.is_(None),
        Item.file_wanted.is_(wanted),
    ]
    if section == "file":
        return [*found, Item.id.not_in(_with_files())]
    return [
        *found,
        Item.id.in_(_with_files()),
        Item.id.in_(_journal_without_file()),
    ]


def hidden_conditions() -> list[ColumnElement[bool]]:
    """Papers marked as needing no (further) file, of either section."""
    return [
        Item.deleted_at.is_(None),
        Item.archived_at.is_(None),
        Item.file_wanted.is_(False),
        or_(Item.id.not_in(_with_files()), Item.id.in_(_journal_without_file())),
    ]


def journal_version(item: Item) -> Version | None:
    """The published (or accepted) version that has no file yet."""
    for version in item.versions:
        if version.kind in JOURNAL and not any(
            f.deleted_at is None for f in version.files
        ):
            return version
    return None


def journal_doi(item: Item) -> str | None:
    version = journal_version(item)
    if version is None:
        return None
    for identifier in version.identifiers:
        if identifier.scheme == Scheme.DOI and not is_arxiv_doi(identifier.value):
            return identifier.value
    return None


def never_tried(
    db: Session, *, added_before: datetime, limit: int
) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
    """Papers without a file, with a DOI or arXiv ID, never tried for an
    open-access copy (and added before ``added_before``, so a browser that
    sends the PDF right after the paper gets there first); with who added
    them."""
    with_id = (
        select(Version.item_id)
        .join(Identifier)
        .where(Identifier.scheme.in_([Scheme.DOI, Scheme.ARXIV]))
    )
    rows = db.execute(
        select(Item.id, Item.added_by)
        .where(
            *conditions(),
            Item.open_access_tried_at.is_(None),
            Item.created_at < added_before,
            Item.id.in_(with_id),
        )
        .order_by(Item.id)
        .limit(limit)
    )
    return [(item_id, added_by) for item_id, added_by in rows]


def may_have_copy(item: Item, contact_email: str | None) -> bool:
    """Whether the server may find an open-access copy: an arXiv ID, or a
    DOI (its arXiv version via OpenAlex, or Unpaywall with a contact
    email)."""
    return bool(open_access.sources(item, contact_email)) or bool(
        _identifiers(item, Scheme.DOI)
    )


def add_journal_copy(
    db: Session,
    http: httpx2.Client,
    blobs: BlobStore,
    item: Item,
    *,
    contact_email: str | None,
    max_bytes: int,
    user_id: uuid.UUID | None,
) -> File | None:
    """The journal's own open-access copy for the published version that
    has no file (Unpaywall: published or accepted version only); the try is
    noted on the paper. None if none was found. Commits."""
    item.open_access_tried_at = datetime.now(UTC)
    version, doi = journal_version(item), journal_doi(item)
    if version is None or doi is None:
        item.open_access_error = "no published version with a DOI lacks its file"
        db.commit()
        return None
    try:
        stored = open_access.fetch_journal_copy(
            http, blobs, doi, contact_email=contact_email, max_bytes=max_bytes
        )
    except open_access.NoSource as error:
        item.open_access_error = str(error)[:1000]
        db.commit()
        return None
    return _attach(db, item, version, stored, _safe(doi) + ".pdf", user_id)


def _safe(name: str) -> str:
    """For a file name: no characters file systems refuse."""
    return re.sub(r'[\\/:*?"<>|]+', "_", name)


def _filename(item: Item) -> str:
    if arxiv := _identifiers(item, Scheme.ARXIV):
        return f"arXiv {arxiv[0]}.pdf"
    if dois := _identifiers(item, Scheme.DOI):
        return _safe(dois[0]) + ".pdf"
    return "paper.pdf"


def add_open_access(
    db: Session,
    http: httpx2.Client,
    blobs: BlobStore,
    item: Item,
    *,
    contact_email: str | None,
    max_bytes: int,
    user_id: uuid.UUID | None,
) -> File | None:
    """Fetch an open-access copy and add it to the paper's shown version;
    the try is noted on the paper (when, and why nothing was found). None
    if no copy was found. Commits."""
    item.open_access_tried_at = datetime.now(UTC)
    _add_arxiv_version(db, http, item, contact_email, user_id)
    # The journal's own open copy first: then the paper is complete.
    journal, doi = journal_version(item), journal_doi(item)
    if journal is not None and doi is not None:
        try:
            stored = open_access.fetch_journal_copy(
                http, blobs, doi, contact_email=contact_email, max_bytes=max_bytes
            )
        except open_access.NoSource:
            pass
        else:
            return _attach(db, item, journal, stored, _safe(doi) + ".pdf", user_id)
    try:
        stored, url = open_access.fetch(
            http, blobs, item, contact_email=contact_email, max_bytes=max_bytes
        )
    except open_access.NoSource as error:
        item.open_access_error = str(error)[:1000]
        db.commit()
        return None
    version = _version_with_arxiv(item, open_access.arxiv_id_of(url))
    version = version or library.preferred_version(item)
    if version is None:
        item.open_access_error = "the paper has no version"
        db.commit()
        return None
    return _attach(db, item, version, stored, _filename(item), user_id)


def _attach(
    db: Session,
    item: Item,
    version: Version,
    stored: StoredBlob,
    filename: str,
    user_id: uuid.UUID | None,
) -> File:
    db.execute(
        insert(Blob)
        .values(sha256=stored.sha256, size=stored.size)
        .on_conflict_do_nothing()
    )
    file = File(
        version=version,
        blob_sha256=stored.sha256,
        role=FileRole.MAIN,
        filename=filename,
        media_type=PDF,
        source=FileSource.OPEN_ACCESS,
        uploaded_by=user_id,
    )
    db.add(file)
    item.open_access_error = None
    db.commit()
    db.refresh(file)
    return file


def _identifiers(item: Item, scheme: Scheme) -> list[str]:
    return [
        identifier.value
        for version in item.versions
        for identifier in version.identifiers
        if identifier.scheme == scheme
    ]


def _version_with_arxiv(item: Item, arxiv_id: str | None) -> Version | None:
    """The version an arXiv PDF belongs to."""
    if arxiv_id is None:
        return None
    for version in item.versions:
        if any(
            i.scheme == Scheme.ARXIV and i.value == arxiv_id
            for i in version.identifiers
        ):
            return version
    return None


def _add_arxiv_version(
    db: Session,
    http: httpx2.Client,
    item: Item,
    contact_email: str | None,
    user_id: uuid.UUID | None,
) -> None:
    """A paper known only by its (publisher's) DOI: if it is on arXiv too,
    add that as its preprint version (its details from arXiv's DOI). The
    published version stays the one shown and cited."""
    if _identifiers(item, Scheme.ARXIV):
        return
    for doi in _identifiers(item, Scheme.DOI):
        if is_arxiv_doi(doi):
            continue
        arxiv_id = open_access.arxiv_id_for(http, doi, contact_email)
        if arxiv_id is None:
            continue
        arxiv_doi = normalize(Scheme.DOI, f"10.48550/arXiv.{arxiv_id}")
        try:
            csl, kind = metadata.lookup_doi(http, arxiv_doi)
            with db.begin_nested():
                library.add_version(
                    db,
                    item,
                    kind=kind,
                    label=None,
                    csl=csl,
                    source=MetadataSource.LOOKUP,
                    identifiers=[(Scheme.DOI, arxiv_doi), *implied_by_doi(arxiv_doi)],
                    created_by=user_id,
                )
        except (
            metadata.DOINotFound,
            metadata.MetadataUnavailable,
            library.IdentifierTaken,
        ):
            # Not found, or another paper has it (a duplicate to merge).
            continue
        db.refresh(item)
        return
