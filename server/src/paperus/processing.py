"""Turning stored files into searchable chunks."""

import dataclasses
import hashlib
import logging
import uuid
from dataclasses import dataclass

import httpx2
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import abstracts, annotations, layouts, pdf
from paperus.covers import cover_pages
from paperus.identify import identify
from paperus.models import Chunk, File, FileChunk, OcrPage, OcrStatus, TextStatus
from paperus.page_layout import Part
from paperus.storage import BlobStore
from paperus.text import (
    Flow,
    TextChunk,
    chunk_document,
    chunk_flow,
    chunk_pages,
    extract_pdf_pages,
    html_text,
)

log = logging.getLogger(__name__)

PDF = "application/pdf"
TEXT_TYPES = ("text/", "application/json", "application/x-tex")
IMAGE_TYPES = ("image/png", "image/jpeg", "image/tiff", "image/webp")
"""Read by OCR, as one page."""
# A page with fewer characters is taken for a scan (or a picture, or empty).
MIN_PAGE_CHARS = 20


def scanned(text: str) -> bool:
    return len(text.strip()) < MIN_PAGE_CHARS


@dataclass
class _Text:
    chunks: list[TextChunk] | None
    """None: not a kind of file paperus reads (yet)."""
    scans: list[int]
    """Pages (from 0) without text that OCR has not read yet."""
    with_ocr: bool = False
    """Some pages' text comes from OCR."""
    first_pages: list[str] = dataclasses.field(default_factory=list)
    """A PDF's first pages as read (for its abstract), without covers."""
    covers: list[int] = dataclasses.field(default_factory=list)
    """Cover pages (from 1), left out of the text."""


def _read(db: Session, file: File, blobs: BlobStore) -> _Text:
    """The file's text in chunks; scanned pages with the text OCR read. A
    PDF's layouts are worked out and kept on the way: its text is read by
    them."""
    if file.media_type.startswith(TEXT_TYPES):
        data = b"".join(blobs.iter_bytes(file.blob_sha256))
        if file.media_type in ("text/html", "application/xhtml+xml"):
            return _Text(chunk_document(html_text(data)), [])
        return _Text(chunk_document(data.decode(errors="replace")), [])
    pieces = None
    if file.media_type == PDF:
        with blobs.local_file(file.blob_sha256) as path:
            try:
                read = pdf.read(path)
            except pdf.PdfError:
                # Too large or slow to lay out: its pages' text alone.
                log.warning("file %s read without layouts", file.id, exc_info=True)
                pages = extract_pdf_pages(path)
            else:
                pages, pieces = read.pages, read.pieces
                layouts.store(db, file.blob_sha256, read.layouts)
    elif file.media_type in IMAGE_TYPES:
        pages = [""]
    else:
        return _Text(None, [])
    return _pages_text(pages, pieces, _ocr_text(db, file.blob_sha256))


def _ocr_text(db: Session, sha256: bytes) -> dict[int, str]:
    """The text OCR read, by page (from 0)."""
    rows = db.execute(
        select(OcrPage.page, OcrPage.text).where(OcrPage.blob_sha256 == sha256)
    ).all()
    return {page: text for page, text in rows}


def _pages_text(
    pages: list[str], pieces: list[list[Part]] | None, read: dict[int, str]
) -> _Text:
    """Chunks of pages' text (and, by their layouts, their pieces': one
    flow), scanned pages with the text OCR ``read``; covers left out."""
    pages = list(pages)
    scans = []
    own = []
    for index, text in enumerate(pages):
        own.append(not scanned(text))
        if own[-1]:
            continue
        if index in read:
            pages[index] = read[index]
        else:
            scans.append(index)
    with_ocr = any(index in read for index in range(len(pages)))
    covers = cover_pages(pages)
    for number in covers:
        pages[number - 1] = ""  # out of the text; the pages keep their numbers
    first = [text for n, text in enumerate(pages, 1) if n not in covers][:2]
    if pieces is None:
        return _Text(chunk_pages(pages), scans, with_ocr, first, covers)
    parts: list[tuple[str, int, Flow]] = []
    for number, (text, laid_out) in enumerate(zip(pages, pieces, strict=True), 1):
        if number in covers:
            continue
        # A scan's text (by OCR) is not in its layout's pieces: a section
        # of its own.
        if own[number - 1]:
            parts += [(t, number, "caption" if c else "text") for t, c in laid_out]
        else:
            parts.append((text, number, "page"))
    return _Text(chunk_flow(parts), scans, with_ocr, first, covers)


def recut(db: Session, sha256: bytes, read: pdf.Read) -> list[uuid.UUID]:
    """The passages of a PDF's files cut again from its new layouts (after
    the layout code changed); commits. The files (to embed what is new:
    passages whose text stayed keep their vectors)."""
    files = list(
        db.scalars(
            select(File).where(
                File.blob_sha256 == sha256,
                File.media_type == PDF,
                File.text_status == TextStatus.DONE,
            )
        )
    )
    if not files or read.pieces is None:
        return []
    chunks = _pages_text(read.pages, read.pieces, _ocr_text(db, sha256)).chunks
    if not chunks:
        return []
    for file in files:
        db.execute(delete(FileChunk).where(FileChunk.file_id == file.id))
        _store_manifest(db, file, chunks)
    db.commit()
    return [file.id for file in files]


def _store_manifest(db: Session, file: File, chunks: list[TextChunk]) -> None:
    rows = []
    for position, chunk in enumerate(chunks):
        sha256 = hashlib.sha256(chunk.text.encode()).digest()
        db.execute(
            insert(Chunk)
            .values(sha256=sha256, text=chunk.text)
            .on_conflict_do_nothing()
        )
        rows.append(
            FileChunk(
                file_id=file.id,
                position=position,
                chunk_sha256=sha256,
                page=chunk.page,
                in_references=chunk.references,
                caption=chunk.caption,
            )
        )
    db.add_all(rows)


def _copy_manifest(db: Session, file: File) -> bool:
    """Reuse the chunks of another file with the same contents, if any."""
    source = db.scalar(
        select(File)
        .where(
            File.blob_sha256 == file.blob_sha256,
            File.text_status == TextStatus.DONE,
            File.id != file.id,
        )
        .limit(1)
    )
    if source is None:
        return False
    file.ocr_status = source.ocr_status
    file.cover_pages = source.cover_pages
    for row in db.scalars(select(FileChunk).where(FileChunk.file_id == source.id)):
        db.add(
            FileChunk(
                file_id=file.id,
                position=row.position,
                chunk_sha256=row.chunk_sha256,
                page=row.page,
                in_references=row.in_references,
                caption=row.caption,
            )
        )
    return True


def _identify(
    db: Session,
    blobs: BlobStore,
    http: httpx2.Client | None,
    file: File,
    first_pages: list[str] | None = None,
) -> None:
    """Metadata from the text (``first_pages``: as read, with their running
    headers and margins: a DOI or arXiv's stamp may be there), in the same
    transaction, so the item is only shown as done when its title is too.
    Failures keep the text."""
    if http is None:
        return
    db.flush()
    text = "\n".join(first_pages) if first_pages is not None else None
    try:
        with db.begin_nested():
            identify(db, blobs, http, file.id, text)
    except Exception:
        log.warning("identifying file %s failed", file.id, exc_info=True)


def _take_in_annotations(db: Session, blobs: BlobStore, file: File) -> None:
    """A PDF's own annotations, once, as its uploader's (see
    ``paperus.annotations``); a PDF they cannot be read from keeps them."""
    if file.media_type != PDF or file.file_marks is not None:
        return
    try:
        with blobs.local_file(file.blob_sha256) as path:
            found = pdf.annotations(path)
    except Exception:
        log.warning("annotations of file %s not read", file.id, exc_info=True)
        return
    annotations.take_in(db, file, found)


def process_file(
    db: Session,
    blobs: BlobStore,
    file_id: uuid.UUID,
    http: httpx2.Client | None = None,
    *,
    ocr: bool = True,
) -> bool:
    """Extract and chunk the text of a pending file, identify it, and commit.

    ``http`` is for looking up identifiers found in the text; without it,
    uploads keep their placeholder metadata. Scanned pages wait for OCR
    (``paperus.ocr``) if ``ocr``, and the file is read again once they are
    read. Returns whether pages wait for OCR.
    """
    # Only the file's row: its content (joined in) is shared with other
    # files, and locking it too made uploads of the same file deadlock.
    file = db.get(File, file_id, with_for_update={"of": File})
    if file is None or file.text_status != TextStatus.PENDING:
        return False
    if _copy_manifest(db, file):
        file.text_status = TextStatus.DONE
        _identify(db, blobs, http, file)
        _take_in_annotations(db, blobs, file)
        db.commit()
        return file.ocr_status == OcrStatus.PENDING
    try:
        read = _read(db, file, blobs)
    except Exception as error:
        log.warning("text extraction failed for file %s", file_id, exc_info=True)
        file.text_status = TextStatus.FAILED
        file.text_error = f"{type(error).__name__}: {error}"[:500]
        db.commit()
        return False
    file.cover_pages = read.covers
    if read.scans:
        file.ocr_status = OcrStatus.PENDING if ocr else OcrStatus.SKIPPED
    else:
        file.ocr_status = OcrStatus.DONE if read.with_ocr else None
    chunks = read.chunks
    if chunks is None:
        file.text_status = TextStatus.UNSUPPORTED
    elif not chunks:
        file.text_status = TextStatus.NO_TEXT
    else:
        _store_manifest(db, file, chunks)
        file.text_status = TextStatus.DONE
        _identify(db, blobs, http, file, read.first_pages)
        # Without one in its details: the abstract the PDF begins with.
        if file.version is not None:
            found = abstracts.from_pages(read.first_pages)
            abstracts.take(file.version.item, found, replace=False)
        _take_in_annotations(db, blobs, file)
    db.commit()
    return file.ocr_status == OcrStatus.PENDING


def pending_files(db: Session, limit: int = 500) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(File.id)
            .where(File.text_status == TextStatus.PENDING)
            .order_by(File.id)
            .limit(limit)
        )
    )


def reread_failed(db: Session) -> int:
    """Try the files whose reading failed once more (e.g. after a fix);
    commits; how many. They are not retried by themselves: a broken file
    would fail for ever."""
    result = db.execute(
        update(File)
        .where(File.deleted_at.is_(None), File.text_status == TextStatus.FAILED)
        .values(text_status=TextStatus.PENDING, text_error=None)
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def reread_all(db: Session) -> int:
    """Read every file again (e.g. after chunking changed); commits.

    Manifests are rebuilt; chunks and their vectors are kept, so unchanged
    passages are not embedded again. Metadata is only replaced for items that
    still have placeholder metadata from their file.
    """
    db.execute(delete(FileChunk))
    active = File.deleted_at.is_(None)
    count = db.scalar(select(func.count()).select_from(File).where(active)) or 0
    db.execute(
        update(File)
        .where(active)
        .values(text_status=TextStatus.PENDING, text_error=None)
    )
    db.commit()
    return count
