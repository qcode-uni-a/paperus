"""Imports from other reference managers (Zotero, JabRef, Mendeley, …), and
of the references of LaTeX sources (arXiv papers).

The upload is stored and imported by the worker; the page follows its
progress. See docs/ingestion.md.
"""

import re
import uuid
from collections.abc import Iterable, Iterator, Sequence
from contextlib import ExitStack
from datetime import datetime
from typing import Annotated, Any, BinaryIO

import httpx2
from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi import File as FormFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.identifiers import InvalidIdentifier, normalize_arxiv
from paperus.importing import mapping, paperus_export
from paperus.importing.choices import Choices, ExportNames, Preview
from paperus.importing.run import forget_upload
from paperus.jobs import queue_import
from paperus.models import Blob, Import, ImportPart, ImportStatus
from paperus.storage import BlobStore, TooLarge

router = APIRouter(tags=["imports"])

CHUNK_SIZE = 1024 * 1024


class ImportOut(BaseModel):
    id: uuid.UUID
    filename: str
    library_id: uuid.UUID
    format: str | None
    """bibtex, ris or csl-json, once read."""
    status: ImportStatus
    done: int
    total: int
    report: dict[str, Any] | None
    """Counts (papers, added, found, files, notes, collections), missing
    files and problems, when done."""
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    choices: paperus_export.ImportChoices | None = None
    """A paperus export: its owners and parts, waiting for the person to
    choose where its owners go (status ``needs_choices``)."""


def import_out(record: Import) -> ImportOut:
    return ImportOut(
        id=record.id,
        filename=record.filename,
        library_id=record.library_id,
        format=record.format,
        status=ImportStatus(record.status),
        done=record.done,
        total=record.total,
        report=record.report,
        error=record.error,
        created_at=record.created_at,
        finished_at=record.finished_at,
        choices=(
            paperus_export.ImportChoices.model_validate(record.choices)
            if record.choices
            else None
        ),
    )


def _chunks(stream: BinaryIO) -> Iterator[bytes]:
    while chunk := stream.read(CHUNK_SIZE):
        yield chunk


@router.post("/api/imports", status_code=201)
def start_import(
    upload: UploadFile,
    request: Request,
    db: DB,
    access: CurrentAccess,
    library_id: Annotated[uuid.UUID | None, Form()] = None,
    parts: Annotated[list[UploadFile] | None, FormFile()] = None,
) -> ImportOut:
    """Import an export: BibTeX, RIS or CSL-JSON, alone or zipped with its
    files, a LaTeX source (.tar.gz, .bbl) for its references, or a paperus
    export (with ``parts``: its other zips). Everything new belongs to
    ``library_id`` (default: the person's default owner); a paperus export
    waits for the person to choose where its owners go (``start``). Runs in
    the background; poll ``GET /api/imports/{id}``."""
    owner = access.target_library(library_id)
    uploads = [(_chunks(upload.file), upload.filename or "export")] + [
        (_chunks(part.file), part.filename or "part") for part in parts or []
    ]
    return _start(request, db, access, owner, uploads)


def _store(request: Request, db: Session, chunks: Iterable[bytes]) -> bytes:
    blobs: BlobStore = request.app.state.blobs
    try:
        stored = blobs.put(chunks, max_size=request.app.state.settings.max_import_bytes)
    except TooLarge as error:
        raise HTTPException(413, "file too large") from error
    db.execute(
        insert(Blob)
        .values(sha256=stored.sha256, size=stored.size)
        .on_conflict_do_nothing()
    )
    db.commit()
    return stored.sha256


def _store_all(
    request: Request, db: Session, uploads: Sequence[tuple[Iterable[bytes], str]]
) -> list[tuple[bytes, str]]:
    """Store the uploads; none of them if one is too large."""
    stored: list[tuple[bytes, str]] = []
    try:
        for chunks, filename in uploads:
            stored.append((_store(request, db, chunks), filename[:255]))
    except HTTPException:
        _forget(request, db, [sha for sha, _ in stored])
        raise
    return stored


def _forget(request: Request, db: Session, shas: list[bytes]) -> None:
    for sha in shas:
        forget_upload(db, request.app.state.blobs, sha)


def _start(
    request: Request,
    db: Session,
    access: Access,
    owner: uuid.UUID,
    uploads: Sequence[tuple[Iterable[bytes], str]],
) -> ImportOut:
    """Store the uploads and queue their import; a paperus export waits for
    the person's choices instead."""
    stored = _store_all(request, db, uploads)
    record = Import(
        user_id=access.user.id,
        library_id=owner,
        filename=stored[0][1],
        blob_sha256=stored[0][0],
        status=ImportStatus.WAITING,
    )
    db.add(record)
    db.commit()
    try:
        is_paperus = _take(request, db, access, record, stored)
    except HTTPException:
        db.delete(record)
        db.commit()
        _forget(request, db, [sha for sha, _ in stored])
        raise
    if not is_paperus:
        if len(stored) > 1:
            db.delete(record)
            db.commit()
            _forget(request, db, [sha for sha, _ in stored])
            raise HTTPException(
                422, "Choose one file (only a paperus export comes in several)."
            )
        queue_import(request.app.state.jobs, record.id, owner)
    return import_out(record)


def _take(
    request: Request,
    db: Session,
    access: Access,
    record: Import,
    stored: list[tuple[bytes, str]],
) -> bool:
    """If the uploads are (parts of) a paperus export: keep its parts with
    the import, which then waits for the person's choices; uploads that are
    not its parts are dropped. Whether it is one."""
    blobs: BlobStore = request.app.state.blobs
    with ExitStack() as stack:
        uploads = [
            paperus_export.Upload(stack.enter_context(blobs.local_file(sha)), name)
            for sha, name in stored
        ]
        try:
            if not paperus_export.is_export(uploads):
                return False
            with paperus_export.opened(uploads, blobs.temp_dir) as opened:
                choices = opened.choices
                names = mapping.read_names(opened)
        except paperus_export.NotAnExport as error:
            raise HTTPException(422, str(error)) from error
        parts: list[tuple[int, bytes, str]] = []
        dropped: list[bytes] = []
        for upload, (sha, name) in zip(uploads, stored, strict=True):
            marker = paperus_export.read_marker(upload)
            if (
                marker is None
                or marker.export_id != choices.export_id
                or any(sha == known for _, known, _ in parts)
            ):
                dropped.append(sha)
            else:
                parts.append((marker.part, sha, name))
    parts.sort()
    mapping.describe_owners(db, access, choices)
    record.format = paperus_export.NAME
    record.status = ImportStatus.NEEDS_CHOICES
    # The export's tags and collections are kept for comparing (not shown).
    record.choices = {
        **choices.model_dump(mode="json"),
        "names": names.model_dump(mode="json"),
    }
    record.blob_sha256 = parts[0][1]
    record.filename = parts[0][2]
    record.parts = [
        ImportPart(position=n, filename=name, blob_sha256=sha)
        for n, (_, sha, name) in enumerate(parts[1:], 1)
    ]
    db.commit()
    _forget(request, db, [sha for sha in dropped if sha not in {p[1] for p in parts}])
    return True


def _own_import(db: Session, access: Access, import_id: uuid.UUID) -> Import:
    record = db.get(Import, import_id)
    if record is None or record.user_id != access.user.id:
        raise HTTPException(404, "import not found")
    return record


def _waiting_for_choices(db: Session, access: Access, import_id: uuid.UUID) -> Import:
    record = _own_import(db, access, import_id)
    if record.status != ImportStatus.NEEDS_CHOICES:
        raise HTTPException(409, "this import is not waiting for choices")
    return record


@router.post("/api/imports/{import_id}/parts")
def add_import_parts(
    import_id: uuid.UUID,
    parts: Annotated[list[UploadFile], FormFile()],
    request: Request,
    db: DB,
    access: CurrentAccess,
) -> ImportOut:
    """More zips of a paperus export waiting for choices (parts missing so
    far); those of another export are left out."""
    record = _waiting_for_choices(db, access, import_id)
    new = _store_all(
        request, db, [(_chunks(p.file), p.filename or "part") for p in parts]
    )
    known = [(record.blob_sha256, record.filename)] + [
        (part.blob_sha256, part.filename) for part in record.parts
    ]
    stored = [(sha, name) for sha, name in known if sha is not None] + new
    try:
        _take(request, db, access, record, stored)
    except HTTPException:
        _forget(request, db, [sha for sha, _ in new])
        raise
    return import_out(record)


def _stored(record: Import) -> tuple[paperus_export.ImportChoices, ExportNames]:
    stored = record.choices or {}
    return (
        paperus_export.ImportChoices.model_validate(stored),
        ExportNames.model_validate(stored.get("names") or {}),
    )


def _answer(error: Exception) -> HTTPException:
    """A choice that cannot be followed, as the API says it."""
    if isinstance(error, mapping.Refused):
        return HTTPException(403, str(error))
    if isinstance(error, LookupError):
        return HTTPException(404, str(error).strip("'\""))
    return HTTPException(422, str(error))


@router.post("/api/imports/{import_id}/preview")
def preview_paperus_import(
    import_id: uuid.UUID, body: Choices, db: DB, access: CurrentAccess
) -> Preview:
    """For these owner choices: the export's tags and collections whose
    names clash with (or are like) those where they go, each with its
    default and suggestions (docs/import-mapping.md)."""
    record = _waiting_for_choices(db, access, import_id)
    export_choices, names = _stored(record)
    try:
        return mapping.preview(db, access, export_choices, names, body)
    except (mapping.Refused, LookupError, ValueError) as error:
        raise _answer(error) from error


@router.post("/api/imports/{import_id}/start")
def start_paperus_import(
    import_id: uuid.UUID,
    body: Choices,
    request: Request,
    db: DB,
    access: CurrentAccess,
) -> ImportOut:
    """Import a paperus export as the person chose: where its owners go,
    and what its clashing tags and collections become (what is not named
    takes its default)."""
    record = _waiting_for_choices(db, access, import_id)
    export_choices, names = _stored(record)
    try:
        mapping.check(db, access, export_choices, names, body)
    except (mapping.Refused, LookupError, ValueError) as error:
        raise _answer(error) from error
    export_choices.mapping = body
    record.choices = {
        **export_choices.model_dump(mode="json"),
        "names": names.model_dump(mode="json"),
    }
    record.library_id = access.own_library
    record.status = ImportStatus.WAITING
    db.commit()
    queue_import(request.app.state.jobs, record.id, record.library_id)
    return import_out(record)


@router.delete("/api/imports/{import_id}", status_code=204)
def delete_import(
    import_id: uuid.UUID, request: Request, db: DB, access: CurrentAccess
) -> None:
    """Remove an import from the list (one waiting for choices: drop it
    with its uploads); not while it runs."""
    record = _own_import(db, access, import_id)
    if record.status in (ImportStatus.WAITING, ImportStatus.RUNNING):
        raise HTTPException(409, "the import is running")
    uploads = [record.blob_sha256, *(part.blob_sha256 for part in record.parts)]
    db.delete(record)
    db.commit()
    _forget(request, db, [sha for sha in uploads if sha is not None])


class ArxivImportIn(BaseModel):
    arxiv_id: str
    """``2401.12345``, ``arXiv:2401.12345v2``, ``hep-th/9901001`` or a link
    to the paper on arxiv.org."""
    library_id: uuid.UUID | None = None


E_PRINT = "https://arxiv.org/e-print/"
_ARXIV_LINK = re.compile(
    r"^(?:https?://(?:www\.|export\.)?arxiv\.org/(?:abs|pdf|e-print|src)/)?"
    r"(?:arxiv:)?(.+?)(?:\.pdf)?/?$",
    re.IGNORECASE,
)


def arxiv_paper(value: str) -> str:
    """The arXiv ID (with its version, if given) in what was typed."""
    found = _ARXIV_LINK.match(value.strip())
    paper = found.group(1) if found else ""
    try:
        normalize_arxiv(paper)
    except InvalidIdentifier as error:
        raise HTTPException(422, "not an arXiv ID or link") from error
    return paper


@router.post("/api/imports/arxiv", status_code=201)
def import_arxiv(
    body: ArxivImportIn, request: Request, db: DB, access: CurrentAccess
) -> ImportOut:
    """Import the references of an arXiv paper: its LaTeX source is
    downloaded from arXiv (one request) and imported as an upload would be,
    into a collection named after the paper."""
    owner = access.target_library(body.library_id)
    paper = arxiv_paper(body.arxiv_id)
    http: httpx2.Client = request.app.state.http
    try:
        with http.stream("GET", E_PRINT + paper, timeout=120) as response:
            if response.status_code == 404:
                raise HTTPException(404, "arXiv has no paper of this ID")
            if response.status_code != 200:
                raise HTTPException(
                    502, f"arXiv answered {response.status_code}; try again later"
                )
            chunks = response.iter_bytes(CHUNK_SIZE)
            first = next(chunks, b"")
            if first.startswith(b"%PDF"):
                raise HTTPException(
                    422, "arXiv has only a PDF of this paper, no LaTeX source"
                )
            return _start(
                request,
                db,
                access,
                owner,
                [(_together(first, chunks), f"arXiv:{paper}")],
            )
    except httpx2.HTTPError as error:
        raise HTTPException(502, "arXiv could not be reached; try again") from error


def _together(first: bytes, rest: Iterator[bytes]) -> Iterator[bytes]:
    yield first
    yield from rest


@router.get("/api/imports")
def list_imports(db: DB, access: CurrentAccess) -> list[ImportOut]:
    """The person's imports, newest first."""
    records = db.scalars(
        select(Import)
        .where(Import.user_id == access.user.id)
        .order_by(Import.created_at.desc())
        .limit(20)
    )
    return [import_out(record) for record in records]


@router.get("/api/imports/{import_id}")
def get_import(import_id: uuid.UUID, db: DB, access: CurrentAccess) -> ImportOut:
    record = db.get(Import, import_id)
    if record is None or record.user_id != access.user.id:
        raise HTTPException(404, "import not found")
    return import_out(record)
