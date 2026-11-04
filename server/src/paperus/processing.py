"""Turning stored files into searchable chunks."""

import hashlib
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus.models import Chunk, File, FileChunk, TextStatus
from paperus.storage import BlobStore
from paperus.text import TextChunk, chunk_pages, chunk_text, extract_pdf_pages

log = logging.getLogger(__name__)

PDF = "application/pdf"
TEXT_TYPES = ("text/", "application/json", "application/x-tex")


def _chunks_for(file: File, blobs: BlobStore) -> list[TextChunk] | None:
    """Chunks of the file's text; ``None`` for unsupported file types."""
    if file.media_type == PDF:
        with blobs.local_file(file.blob_sha256) as path:
            return chunk_pages(extract_pdf_pages(path))
    if file.media_type.startswith(TEXT_TYPES):
        data = b"".join(blobs.iter_bytes(file.blob_sha256))
        return chunk_text(data.decode(errors="replace"))
    return None


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
                file_id=file.id, position=position, chunk_sha256=sha256, page=chunk.page
            )
        )
    db.add_all(rows)


def _copy_manifest(db: Session, file: File) -> bool:
    """Reuse the chunks of another file with the same contents, if any."""
    source = db.scalar(
        select(File.id)
        .where(
            File.blob_sha256 == file.blob_sha256,
            File.text_status == TextStatus.DONE,
            File.id != file.id,
        )
        .limit(1)
    )
    if source is None:
        return False
    for row in db.scalars(select(FileChunk).where(FileChunk.file_id == source)):
        db.add(
            FileChunk(
                file_id=file.id,
                position=row.position,
                chunk_sha256=row.chunk_sha256,
                page=row.page,
            )
        )
    return True


def process_file(db: Session, blobs: BlobStore, file_id: uuid.UUID) -> None:
    """Extract and chunk the text of a pending file, and commit."""
    file = db.get(File, file_id, with_for_update=True)
    if file is None or file.text_status != TextStatus.PENDING:
        return
    if _copy_manifest(db, file):
        file.text_status = TextStatus.DONE
        db.commit()
        return
    try:
        chunks = _chunks_for(file, blobs)
    except Exception as error:
        log.warning("text extraction failed for file %s", file_id, exc_info=True)
        file.text_status = TextStatus.FAILED
        file.text_error = f"{type(error).__name__}: {error}"[:500]
        db.commit()
        return
    if chunks is None:
        file.text_status = TextStatus.UNSUPPORTED
    elif not chunks:
        file.text_status = TextStatus.NO_TEXT
    else:
        _store_manifest(db, file, chunks)
        file.text_status = TextStatus.DONE
    db.commit()


def pending_files(db: Session, limit: int = 500) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(File.id)
            .where(File.text_status == TextStatus.PENDING)
            .order_by(File.id)
            .limit(limit)
        )
    )
