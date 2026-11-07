"""Imports from other reference managers (Zotero, JabRef, Mendeley, …), and
of the references of LaTeX sources (arXiv papers).

The upload is stored and imported by the worker; the page follows its
progress. See docs/ingestion.md.
"""

import re
import uuid
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Annotated, Any, BinaryIO

import httpx2
from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.identifiers import InvalidIdentifier, normalize_arxiv
from paperus.jobs import queue_import
from paperus.models import Blob, Import, ImportStatus
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
) -> ImportOut:
    """Import an export: BibTeX, RIS or CSL-JSON, alone or zipped with its
    files, or a LaTeX source (.tar.gz, .bbl) for its references. Everything
    new belongs to ``library_id`` (default: the person's default owner).
    Runs in the background; poll ``GET /api/imports/{id}``."""
    owner = access.target_library(library_id)
    return _start(
        request, db, access, owner, _chunks(upload.file), upload.filename or "export"
    )


def _start(
    request: Request,
    db: Session,
    access: Access,
    owner: uuid.UUID,
    chunks: Iterable[bytes],
    filename: str,
) -> ImportOut:
    """Store the upload and queue its import."""
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
    record = Import(
        user_id=access.user.id,
        library_id=owner,
        filename=filename[:255],
        blob_sha256=stored.sha256,
        status=ImportStatus.WAITING,
    )
    db.add(record)
    db.commit()
    queue_import(request.app.state.jobs, record.id, owner)
    return import_out(record)


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
                request, db, access, owner, _together(first, chunks), f"arXiv:{paper}"
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
