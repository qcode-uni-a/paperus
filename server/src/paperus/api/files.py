"""Files of versions: upload and download."""

import mimetypes
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, BinaryIO

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert

from paperus import library
from paperus.api.deps import DB, CurrentUser
from paperus.models import Blob, File, FileRole, FileSource, Item, Version
from paperus.storage import BlobStore, TooLarge

router = APIRouter(tags=["files"])

CHUNK_SIZE = 1024 * 1024
PDF = "application/pdf"


class FileOut(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    role: FileRole
    filename: str
    media_type: str
    size: int
    sha256: str
    source: FileSource
    created_at: datetime


def file_out(file: File) -> FileOut:
    return FileOut(
        id=file.id,
        version_id=file.version_id,
        role=FileRole(file.role),
        filename=file.filename,
        media_type=file.media_type,
        size=file.blob.size,
        sha256=file.blob_sha256.hex(),
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


def _store_upload(
    version: Version,
    upload: UploadFile,
    role: FileRole,
    request: Request,
    db: DB,
    user_id: uuid.UUID,
) -> FileOut:
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
        version_id=version.id,
        blob_sha256=stored.sha256,
        role=role,
        filename=filename,
        media_type=media_type,
        source=FileSource.UPLOAD,
        uploaded_by=user_id,
    )
    db.add(file)
    db.commit()
    db.refresh(file)
    return file_out(file)


@router.post("/api/versions/{version_id}/files", status_code=201)
def upload_to_version(
    version_id: uuid.UUID,
    upload: UploadFile,
    request: Request,
    db: DB,
    user: CurrentUser,
    role: Annotated[FileRole, Form()] = FileRole.MAIN,
) -> FileOut:
    version = db.get(Version, version_id)
    if version is None:
        raise HTTPException(404, "version not found")
    return _store_upload(version, upload, role, request, db, user.id)


@router.post("/api/items/{item_id}/files", status_code=201)
def upload_to_item(
    item_id: uuid.UUID,
    upload: UploadFile,
    request: Request,
    db: DB,
    user: CurrentUser,
    role: Annotated[FileRole, Form()] = FileRole.MAIN,
) -> FileOut:
    """Upload to the item's preferred version."""
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    version = library.preferred_version(item)
    if version is None:
        raise HTTPException(409, "item has no version")
    return _store_upload(version, upload, role, request, db, user.id)


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
