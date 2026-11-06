"""Embedding chunks for search by meaning."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus.ml import MLClient
from paperus.models import (
    Chunk,
    Embedding,
    File,
    FileChunk,
    Note,
    NoteChunk,
    TextStatus,
)

log = logging.getLogger(__name__)

BATCH = 32


def missing_chunks(db: Session, file_id: uuid.UUID, model: str) -> list[Chunk]:
    """The file's chunks without a vector from ``model`` (shared chunks count).

    Reference lists are left out: they match many queries by meaning (titles
    of other papers) and would push the paper's own text down."""
    has_vector = select(Embedding.chunk_sha256).where(Embedding.model == model)
    return list(
        db.scalars(
            select(Chunk)
            .join(FileChunk, FileChunk.chunk_sha256 == Chunk.sha256)
            .where(
                FileChunk.file_id == file_id,
                FileChunk.in_references.is_(False),
                Chunk.sha256.not_in(has_vector),
            )
            .distinct()
        )
    )


def embed_file(db: Session, ml: MLClient, model: str, file_id: uuid.UUID) -> int:
    """Embed the file's missing chunks, committing per batch; returns the count."""
    vectors = ml.vectors_name(model)
    return _embed(db, ml, model, vectors, missing_chunks(db, file_id, vectors))


def embed_note(db: Session, ml: MLClient, model: str, note_id: uuid.UUID) -> int:
    """Embed the note's chunks that lack a vector; returns the count."""
    vectors = ml.vectors_name(model)
    has_vector = select(Embedding.chunk_sha256).where(Embedding.model == vectors)
    chunks = list(
        db.scalars(
            select(Chunk)
            .join(NoteChunk, NoteChunk.chunk_sha256 == Chunk.sha256)
            .where(NoteChunk.note_id == note_id, Chunk.sha256.not_in(has_vector))
            .distinct()
        )
    )
    return _embed(db, ml, model, vectors, chunks)


def _embed(
    db: Session, ml: MLClient, model: str, vectors: str, chunks: list[Chunk]
) -> int:
    """Stored as ``vectors`` (the model's name, or with its file's variant);
    as the service says it, should it run another file meanwhile."""
    for start in range(0, len(chunks), BATCH):
        batch = chunks[start : start + BATCH]
        embedded = ml.embed_named([c.text for c in batch], model=model, kind="passage")
        if embedded.vectors != vectors:
            log.warning("the ML service now gives %s vectors", embedded.vectors)
        db.execute(
            insert(Embedding)
            .values(
                [
                    {
                        "chunk_sha256": c.sha256,
                        "model": embedded.vectors,
                        "embedding": v,
                    }
                    for c, v in zip(batch, embedded.values, strict=True)
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
                FileChunk.in_references.is_(False),
                FileChunk.chunk_sha256.not_in(has_vector),
            )
            .group_by(File.id)
            .order_by(File.id)
            .limit(limit)
        )
    )


def notes_missing_embeddings(
    db: Session, model: str, limit: int = 500
) -> list[uuid.UUID]:
    """Non-trashed notes with chunks lacking a vector from ``model``."""
    has_vector = select(Embedding.chunk_sha256).where(Embedding.model == model)
    return list(
        db.scalars(
            select(Note.id)
            .join(NoteChunk, NoteChunk.note_id == Note.id)
            .where(Note.deleted_at.is_(None), NoteChunk.chunk_sha256.not_in(has_vector))
            .group_by(Note.id)
            .order_by(Note.id)
            .limit(limit)
        )
    )
