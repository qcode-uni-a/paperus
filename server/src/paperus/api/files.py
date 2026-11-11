"""Files of versions: upload and download."""

import logging
import mimetypes
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, BinaryIO
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import library, open_access, page_layout, system
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.jobs import LAYOUT_ASKED, queue_layout, queue_text_extraction
from paperus.models import (
    Blob,
    Chunk,
    File,
    FileChunk,
    FileRole,
    FileSource,
    Item,
    MetadataSource,
    OcrStatus,
    PageLayouts,
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
    text_error: str | None = None
    """Why reading the text failed (with ``text_status`` "failed")."""
    ocr_status: OcrStatus | None = None
    """Its scanned pages (no text layer): waiting for OCR, read, skipped
    (OCR off), failed; None if it has none."""
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
        text_error=file.text_error,
        ocr_status=OcrStatus(file.ocr_status) if file.ocr_status else None,
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
            _chunks(upload.file),
            max_size=system.max_upload_bytes(db, request.app.state.settings),
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


def _known_file(db: DB, sha256: bytes, libraries: list[uuid.UUID]) -> File | None:
    """The first file with this content in an item outside the trash that is
    in one of the libraries (those the person can read)."""
    return db.scalar(
        select(File)
        .join(Version)
        .join(Item)
        .where(
            File.blob_sha256 == sha256,
            File.deleted_at.is_(None),
            Item.deleted_at.is_(None),
            Item.library_id.in_(libraries),
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
def find_upload(sha256: str, db: DB, access: CurrentAccess) -> KnownFile:
    """The item in a library the person can read that already has a file
    with this SHA-256 (hex), so a client can skip uploading it again; 404 if
    there is none."""
    try:
        digest = bytes.fromhex(sha256)
    except ValueError as error:
        raise HTTPException(422, "not a SHA-256 in hex") from error
    file = _known_file(db, digest, access.readable) if len(digest) == 32 else None
    if file is None:
        raise HTTPException(404, "no such file in the library")
    return KnownFile(
        item_id=file.version.item_id,
        file=file_out(file),
    )


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
    already in a library the person can read makes no new item: the answer
    (200, ``existing``) names the item that has it. ``library_id`` (the
    owner): the person's default if not given.
    """
    target = access.target_library(library_id)
    stored = _put_upload(upload, request, db)
    known = _known_file(db, stored.sha256, access.readable)
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
    if version is None or not access.can_read_item(version.item):
        raise HTTPException(404, "version not found")
    access.require_write_item(version.item)
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
    if item is None or not access.can_read_item(item):
        raise HTTPException(404, "item not found")
    access.require_write_item(item)
    version = library.preferred_version(item)
    if version is None:
        raise HTTPException(409, "item has no version")
    return _store_upload(version, upload, role, request, db, access.user.id)


# Saved web pages (Zotero's snapshots) and SVG: shown in a sandbox without
# scripts, and only with what the file holds itself (images, styles, fonts
# inside it): nothing is loaded from elsewhere, so opening one tells no
# publisher about it. Only paperus' own pages may show them in a frame.
WEB_PAGES = {"text/html", "application/xhtml+xml", "image/svg+xml"}
WEB_PAGE_POLICY = (
    "sandbox; default-src 'none'; img-src data: blob:; "
    "style-src 'unsafe-inline' data:; font-src data:; media-src data:; "
    "frame-ancestors 'self'"
)


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
    if file.media_type in WEB_PAGES:
        safety["Content-Security-Policy"] = WEB_PAGE_POLICY
    elif file.media_type != PDF:
        safety["Content-Security-Policy"] = "sandbox"
    # Browsers keep a copy but ask each time (so a file out of reach, or
    # with its content replaced, is never shown from their cache); the
    # content's hash says whether theirs is still it.
    etag = f'"{file.blob_sha256.hex()}"'
    safety |= {"ETag": etag, "Cache-Control": "private, no-cache"}
    if etag in request.headers.get("If-None-Match", "").split(", "):
        return Response(status_code=304, headers=safety)
    if isinstance(blobs, FilesystemStore):
        if not blobs.path(file.blob_sha256).exists():
            if not blobs.reachable():
                raise HTTPException(
                    503,
                    "The folder of stored files is not reachable (a network"
                    " share not mounted?); the file opens when it is back.",
                )
            raise HTTPException(404, "the file's contents are missing")
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


class LayoutPiece(BaseModel):
    """A part of a page, in PDF points from its top left."""

    x: int
    y: int
    width: int
    height: int
    wide: bool
    """Across the page's width (else one column)."""
    span: int
    """The width that fills the screen (both columns' text the same size)."""


class PageLayoutOut(BaseModel):
    width: float
    height: float
    columns: bool
    """Set in two columns (over a good part of the page)."""
    pieces: list[LayoutPiece]
    """In reading order."""


class PageLayoutsOut(BaseModel):
    version: int
    """The layout code that made them (``current``: the server's now)."""
    current: bool
    pages: list[PageLayoutOut]


@router.get(
    "/api/files/{file_id}/layout",
    response_model=PageLayoutsOut,
    responses={202: {"description": "Being worked out: ask again soon"}},
)
def file_layout(
    file_id: uuid.UUID, request: Request, db: DB, access: CurrentAccess
) -> PageLayoutsOut | Response:
    """Fluent mode's pieces of each page of a PDF, worked out on the
    server once per content. 202 while they are being worked out (they are
    then first in line); made by an older version of the code, they are
    given while new ones are made. 404 if the PDF cannot be read."""
    file = _get_file(db, access, file_id)
    if file.media_type != PDF:
        raise HTTPException(404, "not a PDF")
    known = db.get(PageLayouts, file.blob_sha256)
    current = known is not None and known.version == page_layout.VERSION
    if not current:
        queue_layout(request.app.state.jobs, file.blob_sha256, LAYOUT_ASKED)
    if known is None:
        return Response(status_code=202, headers={"Retry-After": "3"})
    if not known.pages:
        raise HTTPException(404, "the PDF's pages could not be read")
    return PageLayoutsOut(version=known.version, current=current, pages=known.pages)


class PassageText(BaseModel):
    page: int | None
    text: str


@router.get("/api/files/{file_id}/passages/{position}")
def passage_text(
    file_id: uuid.UUID, position: int, db: DB, access: CurrentAccess
) -> PassageText:
    """One passage of a file, as read from it (to find it on the page)."""
    _get_file(db, access, file_id)
    row = db.execute(
        select(FileChunk.page, Chunk.text)
        .join(Chunk, Chunk.sha256 == FileChunk.chunk_sha256)
        .where(FileChunk.file_id == file_id, FileChunk.position == position)
    ).first()
    if row is None:
        raise HTTPException(404, "passage not found")
    return PassageText(page=row.page, text=row.text)


def _get_file(
    db: DB, access: Access, file_id: uuid.UUID, *, write: bool = False
) -> File:
    file = db.get(File, file_id)
    if file is None or not access.can_read_item(file.version.item):
        raise HTTPException(404, "file not found")
    if write:
        access.require_write_item(file.version.item)
    return file


class UnreadableFile(BaseModel):
    file_id: uuid.UUID
    filename: str
    media_type: str
    error: str | None
    item_id: uuid.UUID
    item_title: str
    library_id: uuid.UUID
    writable: bool
    """The person may read it again, replace or remove it."""
    can_download: bool = False
    """An open-access copy may be found (arXiv ID, or DOI via Unpaywall)."""


def unreadable(db: Session, access: Access) -> list[tuple[File, Item]]:
    """Files whose text could not be read, with their papers, of the papers
    the person can see (at most 500)."""
    rows = db.execute(
        select(File, Item)
        .join(Version, Version.id == File.version_id)
        .join(Item, Item.id == Version.item_id)
        .where(
            File.text_status == TextStatus.FAILED,
            File.deleted_at.is_(None),
            Item.deleted_at.is_(None),
            Item.library_id.in_(access.readable),
        )
        .order_by(Item.title, File.filename)
        .limit(500)
    ).all()
    return [(file, item) for file, item in rows if access.can_read_item(item)]


@router.get("/api/files/unreadable")
def unreadable_files(
    request: Request, db: DB, access: CurrentAccess
) -> list[UnreadableFile]:
    """Files whose text could not be read, of the papers the person can see
    (Manage → Unsorted): to read again, replace or remove."""
    email = system.load_config(db, request.app.state.settings).contact_email
    return [
        UnreadableFile(
            file_id=file.id,
            filename=file.filename,
            media_type=file.media_type,
            error=file.text_error,
            item_id=item.id,
            item_title=item.title,
            library_id=item.library_id,
            writable=access.can_write_item(item),
            can_download=bool(open_access.sources(item, email)),
        )
        for file, item in unreadable(db, access)
    ]


@router.post("/api/files/{file_id}/download-again")
def download_again(
    file_id: uuid.UUID, request: Request, db: DB, access: CurrentAccess
) -> FileOut:
    """Replace a file (e.g. a damaged PDF) with a fresh open-access copy of
    its paper: from arXiv, or by DOI via Unpaywall; only a whole PDF that
    opens is taken. 409 if none is found."""
    file = _get_file(db, access, file_id, write=True)
    try:
        replace_with_open_access(db, request.app.state, file)
    except open_access.NoSource as error:
        raise HTTPException(409, f"no good copy found: {error}") from error
    return file_out(file)


def replace_with_open_access(db: Session, state: Any, file: File) -> None:  # noqa: ANN401 (the app's state)
    """The file's contents replaced by a fresh open-access copy of its paper
    (``open_access.NoSource`` if none), to be read again. Commits."""
    settings = state.settings
    stored, _ = open_access.fetch(
        state.http,
        state.blobs,
        file.version.item,
        contact_email=system.load_config(db, settings).contact_email,
        max_bytes=system.max_upload_bytes(db, settings),
    )
    db.execute(
        insert(Blob)
        .values(sha256=stored.sha256, size=stored.size)
        .on_conflict_do_nothing()
    )
    # The old content goes when nothing uses it any more (emptying the trash).
    file.blob_sha256 = stored.sha256
    file.media_type = PDF
    file.source = FileSource.OPEN_ACCESS
    file.text_status = TextStatus.PENDING
    file.text_error = None
    db.commit()
    db.refresh(file)
    queue_text_extraction(state.jobs, file.id)


@router.post("/api/files/{file_id}/read-again", status_code=202)
def read_file_again(
    file_id: uuid.UUID, request: Request, db: DB, access: CurrentAccess
) -> FileOut:
    """Read the file's text once more (e.g. after a fix in paperus)."""
    file = _get_file(db, access, file_id, write=True)
    read_again(db, file)
    queue_text_extraction(request.app.state.jobs, file.id)
    return file_out(file)


def read_again(db: Session, file: File) -> None:
    """Its passages dropped (they come back, with their vectors, if
    unchanged) and its text pending. Commits; the caller queues reading."""
    db.execute(delete(FileChunk).where(FileChunk.file_id == file.id))
    file.text_status = TextStatus.PENDING
    file.text_error = None
    db.commit()


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
