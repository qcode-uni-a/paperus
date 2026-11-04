"""Files of items: upload, list and download."""

import mimetypes
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, BinaryIO

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from paperus.api.deps import DB, CurrentUser
from paperus.models import Blob, File, FileSource, Item, VersionType
from paperus.storage import BlobStore, TooLarge

router = APIRouter(tags=["files"])

CHUNK_SIZE = 1024 * 1024
PDF = "application/pdf"


class FileOut(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    filename: str
    media_type: str
    size: int
    sha256: str
    version_type: VersionType
    source: FileSource
    created_at: datetime


def file_out(file: File, size: int) -> FileOut:
    return FileOut(
        id=file.id,
        item_id=file.item_id,
        filename=file.filename,
        media_type=file.media_type,
        size=size,
        sha256=file.blob_sha256.hex(),
        version_type=VersionType(file.version_type),
        source=FileSource(file.source),
        created_at=file.created_at,
    )


def _chunks(stream: BinaryIO) -> Iterator[bytes]:
    while chunk := stream.read(CHUNK_SIZE):
        yield chunk


def _media_type(head: bytes, filename: str, declared: str | None) -> str:
    """Trust the content for PDFs, otherwise the declared type or the name."""
    if head.startswith(b"%PDF-"):
        return PDF
    looks_like_pdf = declared == PDF or filename.lower().endswith(".pdf")
    if looks_like_pdf:
        # Often a publisher's login or error page saved as .pdf.
        raise HTTPException(422, "not a PDF file")
    guessed, _ = mimetypes.guess_type(filename)
    if declared and declared != "application/octet-stream":
        return declared
    return guessed or "application/octet-stream"


@router.post("/api/items/{item_id}/files", status_code=201)
def upload_file(
    item_id: uuid.UUID,
    upload: UploadFile,
    request: Request,
    db: DB,
    user: CurrentUser,
    version_type: Annotated[VersionType, Form()] = VersionType.PUBLISHED,
) -> FileOut:
    if db.get(Item, item_id) is None:
        raise HTTPException(404, "item not found")
    blobs: BlobStore = request.app.state.blobs
    try:
        stored = blobs.put(
            _chunks(upload.file), max_size=request.app.state.settings.max_upload_bytes
        )
    except TooLarge as error:
        raise HTTPException(413, "file too large") from error
    filename = upload.filename or "file"
    media_type = _media_type(stored.head, filename, upload.content_type)

    db.execute(
        insert(Blob)
        .values(sha256=stored.sha256, size=stored.size)
        .on_conflict_do_nothing()
    )
    file = File(
        item_id=item_id,
        blob_sha256=stored.sha256,
        filename=filename,
        media_type=media_type,
        version_type=version_type,
        source=FileSource.UPLOAD,
        uploaded_by=user.id,
    )
    db.add(file)
    db.commit()
    db.refresh(file)
    return file_out(file, stored.size)


@router.get("/api/items/{item_id}/files")
def list_files(item_id: uuid.UUID, db: DB, user: CurrentUser) -> list[FileOut]:
    if db.get(Item, item_id) is None:
        raise HTTPException(404, "item not found")
    rows = db.execute(
        select(File, Blob.size)
        .join(Blob, Blob.sha256 == File.blob_sha256)
        .where(File.item_id == item_id)
        .order_by(File.id)
    )
    return [file_out(file, size) for file, size in rows]


@router.get("/api/files/{file_id}/content")
def download_file(
    file_id: uuid.UUID, request: Request, db: DB, user: CurrentUser
) -> FileResponse:
    file = db.get(File, file_id)
    if file is None:
        raise HTTPException(404, "file not found")
    blobs: BlobStore = request.app.state.blobs
    return FileResponse(
        blobs.path(file.blob_sha256),
        media_type=file.media_type,
        filename=file.filename,
        content_disposition_type="inline",
    )
