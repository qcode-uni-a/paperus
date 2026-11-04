"""Files of versions: upload and download."""

import logging
import mimetypes
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert

from paperus import library
from paperus.api.deps import DB, CurrentUser
from paperus.jobs import queue_text_extraction
from paperus.models import (
    Blob,
    File,
    FileRole,
    FileSource,
    Item,
    MetadataSource,
    TextStatus,
    Version,
    VersionKind,
)
from paperus.storage import BlobStore, FilesystemStore, TooLarge

log = logging.getLogger(__name__)
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
    text_status: TextStatus
    created_at: datetime
    deleted_at: datetime | None


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
        text_status=TextStatus(file.text_status),
        created_at=file.created_at,
        deleted_at=file.deleted_at,
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
    if version.item.deleted_at is not None:
        raise HTTPException(409, "item is in the trash")
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
        version=version,
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
    try:
        queue_text_extraction(request.app.state.jobs, file.id)
    except Exception:
        # The worker's periodic sweep picks up pending files.
        log.warning("could not queue text extraction for %s", file.id, exc_info=True)
    return file_out(file)


class NewItemUpload(BaseModel):
    item_id: uuid.UUID
    file: FileOut


@router.post("/api/uploads", status_code=201)
def upload_new_item(
    upload: UploadFile, request: Request, db: DB, user: CurrentUser
) -> NewItemUpload:
    """A new item from a file, titled after the file until its text tells more.

    The background job looks for a DOI or arXiv ID in the file and replaces
    the placeholder metadata (see ``paperus.identify``).
    """
    title = Path(upload.filename or "").stem or "Untitled"
    item = library.create_item(
        db,
        kind=VersionKind.OTHER,
        label=None,
        csl={"type": "document", "title": title},
        source=MetadataSource.FILE,
        identifiers=[],
        added_by=user.id,
    )
    file = _store_upload(item.versions[0], upload, FileRole.MAIN, request, db, user.id)
    return NewItemUpload(item_id=item.id, file=file)


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
) -> Response:
    file = db.get(File, file_id)
    if file is None:
        raise HTTPException(404, "file not found")
    blobs: BlobStore = request.app.state.blobs
    if isinstance(blobs, FilesystemStore):
        # Supports range requests, which PDF.js uses for large files.
        return FileResponse(
            blobs.path(file.blob_sha256),
            media_type=file.media_type,
            filename=file.filename,
            content_disposition_type="inline",
        )
    return StreamingResponse(
        blobs.iter_bytes(file.blob_sha256),
        media_type=file.media_type,
        headers={
            "Content-Disposition": f"inline; filename*=utf-8''{quote(file.filename)}",
            "Content-Length": str(file.blob.size),
        },
    )


def _get_file(db: DB, file_id: uuid.UUID) -> File:
    file = db.get(File, file_id)
    if file is None:
        raise HTTPException(404, "file not found")
    return file


@router.delete("/api/files/{file_id}", status_code=204)
def trash_file(file_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    """Move to the trash; restorable with ``POST …/restore``."""
    library.trash(_get_file(db, file_id), user.id)
    db.commit()


@router.post("/api/files/{file_id}/restore")
def restore_file(file_id: uuid.UUID, db: DB, user: CurrentUser) -> FileOut:
    file = _get_file(db, file_id)
    library.restore(file)
    db.commit()
    return file_out(file)
