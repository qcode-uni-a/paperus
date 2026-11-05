"""Files of versions: upload and download."""

import logging
import mimetypes
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, BinaryIO
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from paperus import library
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
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


class _Stored(BaseModel):
    sha256: bytes
    filename: str
    media_type: str


def _put_upload(upload: UploadFile, request: Request, db: DB) -> _Stored:
    """Store the upload's bytes (once per content) and check its type."""
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
    return _Stored(sha256=stored.sha256, filename=filename, media_type=media_type)


def _add_file(
    version: Version,
    stored: _Stored,
    role: FileRole,
    request: Request,
    db: DB,
    user_id: uuid.UUID,
) -> FileOut:
    if version.item.deleted_at is not None:
        raise HTTPException(409, "item is in the trash")
    file = File(
        version=version,
        blob_sha256=stored.sha256,
        role=role,
        filename=stored.filename,
        media_type=stored.media_type,
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
    stored = _put_upload(upload, request, db)
    return _add_file(version, stored, role, request, db, user_id)


def _known_file(db: DB, sha256: bytes, library_id: uuid.UUID) -> File | None:
    """The first file with this content in an item of the library outside
    the trash."""
    return db.scalar(
        select(File)
        .join(Version)
        .join(Item)
        .where(
            File.blob_sha256 == sha256,
            File.deleted_at.is_(None),
            Item.deleted_at.is_(None),
            Item.library_id == library_id,
        )
        .order_by(File.created_at)
        .limit(1)
    )


class NewItemUpload(BaseModel):
    item_id: uuid.UUID
    file: FileOut
    existing: bool = False
    """The same file was already in the library; nothing new was made."""


class KnownFile(BaseModel):
    item_id: uuid.UUID
    file: FileOut


@router.get("/api/uploads/{sha256}")
def find_upload(
    sha256: str,
    db: DB,
    access: CurrentAccess,
    library_id: Annotated[uuid.UUID | None, Query(alias="library")] = None,
) -> KnownFile:
    """The item in the library (the person's default if not given) that
    already has a file with this SHA-256 (hex), so a client can skip
    uploading it again; 404 if there is none."""
    target = access.target_library(library_id)
    try:
        digest = bytes.fromhex(sha256)
    except ValueError as error:
        raise HTTPException(422, "not a SHA-256 in hex") from error
    file = _known_file(db, digest, target) if len(digest) == 32 else None
    if file is None:
        raise HTTPException(404, "no such file in the library")
    return KnownFile(item_id=file.version.item_id, file=file_out(file))


@router.post("/api/uploads", status_code=201)
def upload_new_item(
    upload: UploadFile,
    request: Request,
    response: Response,
    db: DB,
    access: CurrentAccess,
    library_id: Annotated[uuid.UUID | None, Form()] = None,
) -> NewItemUpload:
    """A new item from a file, titled after the file until its text tells more.

    The background job looks for a DOI or arXiv ID in the file and replaces
    the placeholder metadata (see ``paperus.identify``). A file that is
    already in the library makes no new item: the answer (200, ``existing``)
    names the item that has it. ``library_id``: the person's default library
    if not given.
    """
    target = access.target_library(library_id)
    stored = _put_upload(upload, request, db)
    known = _known_file(db, stored.sha256, target)
    if known is not None:
        db.commit()
        response.status_code = 200
        return NewItemUpload(
            item_id=known.version.item_id, file=file_out(known), existing=True
        )
    title = Path(stored.filename).stem or "Untitled"
    item = library.create_item(
        db,
        target,
        kind=VersionKind.OTHER,
        label=None,
        csl={"type": "document", "title": title},
        source=MetadataSource.FILE,
        identifiers=[],
        added_by=access.user.id,
    )
    file = _add_file(
        item.versions[0], stored, FileRole.MAIN, request, db, access.user.id
    )
    return NewItemUpload(item_id=item.id, file=file)


@router.post("/api/versions/{version_id}/files", status_code=201)
def upload_to_version(
    version_id: uuid.UUID,
    upload: UploadFile,
    request: Request,
    db: DB,
    access: CurrentAccess,
    role: Annotated[FileRole, Form()] = FileRole.MAIN,
) -> FileOut:
    version = db.get(Version, version_id)
    if version is None or not access.can_read(version.item.library_id):
        raise HTTPException(404, "version not found")
    access.require_write(version.item.library_id)
    return _store_upload(version, upload, role, request, db, access.user.id)


@router.post("/api/items/{item_id}/files", status_code=201)
def upload_to_item(
    item_id: uuid.UUID,
    upload: UploadFile,
    request: Request,
    db: DB,
    access: CurrentAccess,
    role: Annotated[FileRole, Form()] = FileRole.MAIN,
) -> FileOut:
    """Upload to the item's preferred version."""
    item = db.get(Item, item_id)
    if item is None or not access.can_read(item.library_id):
        raise HTTPException(404, "item not found")
    access.require_write(item.library_id)
    version = library.preferred_version(item)
    if version is None:
        raise HTTPException(409, "item has no version")
    return _store_upload(version, upload, role, request, db, access.user.id)


@router.get("/api/files/{file_id}/content")
def download_file(
    file_id: uuid.UUID, request: Request, db: DB, access: CurrentAccess
) -> Response:
    file = _get_file(db, access, file_id)
    blobs: BlobStore = request.app.state.blobs
    # Uploaded files open on paperus's own address. An HTML or SVG file
    # must not run scripts there, so everything but PDFs (which browsers
    # will not show sandboxed) opens in a sandbox; the type is never guessed.
    safety = {"X-Content-Type-Options": "nosniff"}
    if file.media_type != PDF:
        safety["Content-Security-Policy"] = "sandbox"
    if isinstance(blobs, FilesystemStore):
        # Supports range requests, which PDF.js uses for large files.
        return FileResponse(
            blobs.path(file.blob_sha256),
            media_type=file.media_type,
            filename=file.filename,
            content_disposition_type="inline",
            headers=safety,
        )
    return StreamingResponse(
        blobs.iter_bytes(file.blob_sha256),
        media_type=file.media_type,
        headers={
            "Content-Disposition": f"inline; filename*=utf-8''{quote(file.filename)}",
            "Content-Length": str(file.blob.size),
            **safety,
        },
    )


def _get_file(
    db: DB, access: Access, file_id: uuid.UUID, *, write: bool = False
) -> File:
    file = db.get(File, file_id)
    if file is None or not access.can_read(file.version.item.library_id):
        raise HTTPException(404, "file not found")
    if write:
        access.require_write(file.version.item.library_id)
    return file


@router.delete("/api/files/{file_id}", status_code=204)
def trash_file(file_id: uuid.UUID, db: DB, access: CurrentAccess) -> None:
    """Move to the trash; restorable with ``POST …/restore``."""
    library.trash(_get_file(db, access, file_id, write=True), access.user.id)
    db.commit()


@router.post("/api/files/{file_id}/restore")
def restore_file(file_id: uuid.UUID, db: DB, access: CurrentAccess) -> FileOut:
    file = _get_file(db, access, file_id, write=True)
    library.restore(file)
    db.commit()
    return file_out(file)
