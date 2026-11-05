"""Imports from other reference managers (Zotero, JabRef, Mendeley, …).

The upload is stored and imported by the worker; the page follows its
progress. See docs/ingestion.md.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any, BinaryIO

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from paperus.api.deps import DB, CurrentAccess
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
    files. Everything new belongs to ``library_id`` (default: the person's
    default owner). Runs in the background; poll ``GET /api/imports/{id}``."""
    owner = access.target_library(library_id)
    blobs: BlobStore = request.app.state.blobs
    try:
        stored = blobs.put(
            _chunks(upload.file),
            max_size=request.app.state.settings.max_import_bytes,
        )
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
        filename=(upload.filename or "export")[:255],
        blob_sha256=stored.sha256,
        status=ImportStatus.WAITING,
    )
    db.add(record)
    db.commit()
    queue_import(request.app.state.jobs, record.id)
    return import_out(record)


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
