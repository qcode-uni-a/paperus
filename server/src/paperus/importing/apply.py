"""Adding an ``Export`` to paperus: the same for every format.

Papers the person can already see (same identifier or file) are not added
again: what the export brings (tags, collections, notes, files) goes to the
existing paper, as far as the person may change it. See docs/ingestion.md.
"""

import dataclasses
import logging
import mimetypes
import uuid
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import IO, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import library, notes, organize
from paperus.access import Access
from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedFile, ExportedNote, ExportedPaper
from paperus.metadata import version_kind
from paperus.models import (
    Blob,
    Collection,
    CollectionNote,
    File,
    FileRole,
    FileSource,
    Item,
    MetadataSource,
    Note,
    NoteItem,
    Version,
    VersionKind,
)
from paperus.storage import BlobStore, TooLarge

log = logging.getLogger(__name__)

PDF = "application/pdf"
CHUNK = 1024 * 1024


class Files(Protocol):
    """Where the export's files are: a zip, a folder, or nowhere."""

    def open(self, path: str) -> IO[bytes] | None: ...


class NoFiles:
    def open(self, path: str) -> IO[bytes] | None:
        return None


class _ByName:
    """Finds a file by its path in the export, else by its name alone (paths
    from the exporting computer, e.g. ``C:/Users/…/paper.pdf``): among the
    files of that name, the one whose path ends like the wanted one, or the
    only one."""

    def __init__(self, names: list[str]) -> None:
        self.exact = {self._key(name): name for name in names}
        self.by_name: dict[str, list[str]] = {}
        for name in names:
            self.by_name.setdefault(self._basename(name).lower(), []).append(name)

    @staticmethod
    def _key(path: str) -> str:
        return path.replace("\\", "/").lstrip("./").lower()

    @staticmethod
    def _basename(path: str) -> str:
        return path.replace("\\", "/").rsplit("/", 1)[-1]

    def find(self, path: str) -> str | None:
        key = self._key(path)
        if key in self.exact:
            return self.exact[key]
        candidates = self.by_name.get(self._basename(path).lower(), [])
        for name in candidates:
            if key.endswith("/" + self._key(name)):
                return name
        return candidates[0] if len(candidates) == 1 else None


class ZipFiles:
    def __init__(self, archive: zipfile.ZipFile) -> None:
        self.archive = archive
        self.names = _ByName([n for n in archive.namelist() if not n.endswith("/")])

    def open(self, path: str) -> IO[bytes] | None:
        name = self.names.find(path)
        return self.archive.open(name) if name else None


class FolderFiles:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        files = [str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file()]
        self.names = _ByName(files)

    def open(self, path: str) -> IO[bytes] | None:
        name = self.names.find(path)
        return (self.folder / name).open("rb") if name else None


@dataclass
class Report:
    papers: int = 0
    added: int = 0
    found: int = 0
    """Already in the library; what the export brought was added to them."""
    files: int = 0
    notes: int = 0
    collections: int = 0
    missing_files: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass
class _Run:
    db: Session
    blobs: BlobStore
    access: Access
    owner: uuid.UUID
    files: Files
    max_file_bytes: int
    report: Report
    new_files: list[uuid.UUID] = field(default_factory=list)
    seen: dict[tuple[str, str], uuid.UUID] = field(default_factory=dict)
    """Identifiers and file hashes met in this import → item."""
    collections: dict[tuple[str, ...], Collection] = field(default_factory=dict)


def apply(
    db: Session,
    blobs: BlobStore,
    access: Access,
    export: Export,
    files: Files,
    *,
    owner: uuid.UUID,
    max_file_bytes: int,
    progress: Callable[[int, int], None] = lambda done, total: None,
    file_added: Callable[[uuid.UUID], None] = lambda file_id: None,
) -> Report:
    """Add the export for the person, new things owned by ``owner`` (a
    library they may add to); commits after each paper."""
    access.require_write(owner)
    report = Report(papers=len(export.papers), problems=list(export.problems))
    run = _Run(db, blobs, access, owner, files, max_file_bytes, report)
    for path in export.collections:
        _collection(run, path)
    db.commit()
    total = len(export.papers) + len(export.notes)
    for done, paper in enumerate(export.papers, 1):
        name = paper.source_key or str(paper.csl.get("title"))
        _guarded(run, name, lambda paper=paper: _paper(run, paper))
        for file_id in run.new_files:
            file_added(file_id)
        run.new_files.clear()
        progress(done, total)
    for done, standalone in enumerate(export.notes, len(export.papers) + 1):
        name = notes.title_of(standalone.text) or "a note"
        _guarded(run, name, lambda standalone=standalone: _note(run, standalone))
        progress(done, total)
    return report


def _guarded(run: _Run, name: str, step: Callable[[], None]) -> None:
    """One paper or note in its own transaction: if it fails, what it did is
    undone (also in the counts and caches) and the import goes on."""
    counts = dataclasses.replace(run.report, missing_files=[], problems=[])
    seen = dict(run.seen)
    missing = len(run.report.missing_files)
    try:
        step()
        run.db.commit()
    except Exception as error:
        run.db.rollback()
        log.warning("import of %s failed", name, exc_info=True)
        for counter in ("added", "found", "files", "notes", "collections"):
            setattr(run.report, counter, getattr(counts, counter))
        del run.report.missing_files[missing:]
        run.seen = seen
        run.collections.clear()  # some may have been made in this transaction
        run.new_files.clear()
        run.report.problems.append(f"{name}: {_reason(error)}")


def _reason(error: Exception) -> str:
    """A short message: the database's own words, without the SQL."""
    cause = getattr(error, "orig", None) or error
    first = str(cause).strip().splitlines()[0] if str(cause).strip() else ""
    return (first or type(error).__name__)[:200]


def _note(run: _Run, standalone: ExportedNote) -> None:
    """A note on no paper, unless the owner has the same text already
    (imported before)."""
    existing = run.db.scalar(
        select(Note.id).where(
            Note.library_id == run.owner,
            Note.text == standalone.text,
            Note.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return
    note = notes.create(run.db, run.owner, standalone.text, run.access.user.id)
    run.report.notes += 1
    for path in standalone.collections:
        collection = _collection(run, path)
        if run.access.may_hold(collection.library_id, note):
            note.collection_links.append(
                CollectionNote(collection_id=collection.id, added_by=run.access.user.id)
            )


def _collection(run: _Run, path: tuple[str, ...]) -> Collection:
    """The owner's collection at this path, made if missing (an existing one
    of the same name and place is reused, so importing twice adds nothing)."""
    if path in run.collections:
        return run.collections[path]
    parent = _collection(run, path[:-1]) if len(path) > 1 else None
    name = organize.clean_name(path[-1])[:200]
    place = (
        Collection.parent_id == parent.id if parent else Collection.parent_id.is_(None)
    )
    found = run.db.scalar(
        select(Collection)
        .where(Collection.library_id == run.owner, place, Collection.name == name)
        .limit(1)
    )
    if found is None:
        found = Collection(
            library_id=run.owner,
            name=name,
            parent_id=parent.id if parent else None,
            created_by=run.access.user.id,
            change=0,
        )
        run.db.add(found)
        run.db.flush()
        run.report.collections += 1
    run.collections[path] = found
    return found


def _paper(run: _Run, paper: ExportedPaper) -> None:
    access, db = run.access, run.db
    stored = [s for f in paper.files if (s := _store(run, f)) is not None]
    item = _existing(run, paper, [sha for sha, _, _ in stored])
    if item is None:
        item = library.create_item(
            db,
            run.owner,
            kind=_kind(paper),
            label=None,
            csl=paper.csl,
            source=MetadataSource.IMPORT,
            identifiers=paper.identifiers,
            added_by=access.user.id,
        )
        run.report.added += 1
    else:
        run.report.found += 1
    for scheme, value in paper.identifiers:
        run.seen[(scheme.value, value)] = item.id
    for sha, _, _ in stored:
        run.seen[("file", sha.hex())] = item.id

    if access.can_write_item(item):
        _attach_files(run, item, stored)
    for name in paper.tags:
        if access.may_tag(run.owner, item):
            try:
                organize.tag_item(
                    db, item, name[:100], library_id=run.owner, user_id=access.user.id
                )
            except ValueError:
                continue
    for path in paper.collections:
        collection = _collection(run, path)
        if access.may_hold(collection.library_id, item) and not any(
            link.collection_id == collection.id for link in item.collection_links
        ):
            organize.add_to_collection(db, collection, [item.id], access.user.id)
    for text in paper.notes:
        if _has_note(run, item, text):
            continue
        note = notes.create(db, run.owner, text, access.user.id)
        note.item_links.append(NoteItem(item_id=item.id, added_by=access.user.id))
        run.report.notes += 1


def _has_note(run: _Run, item: Item, text: str) -> bool:
    """The same text is a note on the paper already (imported before)."""
    return (
        run.db.scalar(
            select(Note.id)
            .join(NoteItem, NoteItem.note_id == Note.id)
            .where(
                NoteItem.item_id == item.id,
                Note.text == text,
                Note.deleted_at.is_(None),
            )
            .limit(1)
        )
        is not None
    )


def _existing(run: _Run, paper: ExportedPaper, shas: list[bytes]) -> Item | None:
    """The paper if the person can see it already, or if this import added
    it a moment ago (same identifier or file)."""
    for key in [(s.value, v) for s, v in paper.identifiers] + [
        ("file", sha.hex()) for sha in shas
    ]:
        if key in run.seen:
            return run.db.get(Item, run.seen[key])
    known = library.find_identifier(run.db, run.access.readable, paper.identifiers)
    if known is not None:
        item = known.version.item
        if item.deleted_at is not None and run.access.can_write_item(item):
            library.restore(item)  # as when adding the same DOI again
        return item
    key = paper.csl.get("citation-key")
    if isinstance(key, str) and key:
        # The same entry imported before (no identifier or file to go by).
        item = run.db.scalar(
            select(Item)
            .join(Version)
            .where(
                Version.csl["citation-key"].astext == key,
                Item.title == paper.csl.get("title"),
                Item.deleted_at.is_(None),
                Item.library_id.in_(run.access.readable),
            )
            .limit(1)
        )
        if item is not None:
            return item
    for sha in shas:
        item = run.db.scalar(
            select(Item)
            .join(Version)
            .join(File)
            .where(
                File.blob_sha256 == sha,
                File.deleted_at.is_(None),
                Item.deleted_at.is_(None),
                Item.library_id.in_(run.access.readable),
            )
            .limit(1)
        )
        if item is not None:
            return item
    return None


def _kind(paper: ExportedPaper) -> VersionKind:
    schemes = {scheme for scheme, _ in paper.identifiers}
    doi = next((v for s, v in paper.identifiers if s == Scheme.DOI), None)
    if doi:
        return version_kind(doi, paper.csl)
    if Scheme.ARXIV in schemes:
        return VersionKind.PREPRINT
    if paper.csl.get("container-title") or paper.csl.get("publisher"):
        return VersionKind.PUBLISHED
    return VersionKind.OTHER


def _store(run: _Run, exported: ExportedFile) -> tuple[bytes, str, str] | None:
    """The file's content stored once; (sha256, file name, media type)."""
    stream = run.files.open(exported.path)
    if stream is None:
        run.report.missing_files.append(exported.path)
        return None
    try:
        with stream:
            stored = run.blobs.put(_chunks(stream), max_size=run.max_file_bytes)
    except TooLarge:
        run.report.problems.append(f"{exported.path}: too large")
        return None
    name = (
        PureWindowsPath(exported.path).name
        if "\\" in exported.path
        else (PurePosixPath(exported.path).name)
    )
    media_type = (
        PDF
        if stored.head.startswith(b"%PDF-")
        else exported.media_type
        or mimetypes.guess_type(name)[0]
        or "application/octet-stream"
    )
    run.db.execute(
        insert(Blob)
        .values(sha256=stored.sha256, size=stored.size)
        .on_conflict_do_nothing()
    )
    return stored.sha256, name or "file", media_type


def _chunks(stream: IO[bytes]) -> Iterator[bytes]:
    while chunk := stream.read(CHUNK):
        yield chunk


def _attach_files(run: _Run, item: Item, stored: list[tuple[bytes, str, str]]) -> None:
    version = library.preferred_version(item)
    if version is None:
        return
    present = {f.blob_sha256 for v in item.versions for f in v.files}
    has_main = any(f.role == FileRole.MAIN for f in version.files)
    for sha, name, media_type in stored:
        if sha in present:
            continue
        role = (
            FileRole.MAIN
            if media_type == PDF and not has_main
            else FileRole.SUPPLEMENTARY
        )
        has_main = has_main or role == FileRole.MAIN
        file = File(
            version=version,
            blob_sha256=sha,
            role=role,
            filename=name[:255],
            media_type=media_type,
            source=FileSource.IMPORT,
            uploaded_by=run.access.user.id,
        )
        run.db.add(file)
        run.db.flush()
        present.add(sha)
        run.new_files.append(file.id)
        run.report.files += 1
