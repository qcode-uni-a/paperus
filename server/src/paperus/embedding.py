"""Embedding chunks for search by meaning."""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus.ml import MLClient
from paperus.models import Chunk, Embedding, File, FileChunk, TextStatus

BATCH = 32


def missing_chunks(db: Session, file_id: uuid.UUID, model: str) -> list[Chunk]:
    """The file's chunks without a vector from ``model`` (shared chunks count)."""
    has_vector = select(Embedding.chunk_sha256).where(Embedding.model == model)
    return list(
        db.scalars(
            select(Chunk)
            .join(FileChunk, FileChunk.chunk_sha256 == Chunk.sha256)
            .where(FileChunk.file_id == file_id, Chunk.sha256.not_in(has_vector))
            .distinct()
        )
    )


def embed_file(db: Session, ml: MLClient, model: str, file_id: uuid.UUID) -> int:
    """Embed the file's missing chunks, committing per batch; returns the count."""
    chunks = missing_chunks(db, file_id, model)
    for start in range(0, len(chunks), BATCH):
        batch = chunks[start : start + BATCH]
        vectors = ml.embed([c.text for c in batch], model=model, kind="passage")
        db.execute(
            insert(Embedding)
            .values(
                [
                    {"chunk_sha256": c.sha256, "model": model, "embedding": v}
                    for c, v in zip(batch, vectors, strict=True)
                ]
            )
            .on_conflict_do_nothing()
        )
        db.commit()
    return len(chunks)


def files_missing_embeddings(
    db: Session, model: str, limit: int = 500
) -> list[uuid.UUID]:
    """Readable, non-trashed files with chunks lacking a vector from ``model``."""
    has_vector = select(Embedding.chunk_sha256).where(Embedding.model == model)
    return list(
        db.scalars(
            select(File.id)
            .join(FileChunk, FileChunk.file_id == File.id)
            .where(
                File.text_status == TextStatus.DONE,
                File.deleted_at.is_(None),
                FileChunk.chunk_sha256.not_in(has_vector),
            )
            .group_by(File.id)
            .order_by(File.id)
            .limit(limit)
        )
    )
