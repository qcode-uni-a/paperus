"""Emptying the trash: papers, files and notes deleted for good, and stored
contents nothing uses any more removed (Administration → Settings → Trash,
and "Empty trash" on the trash page)."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, delete, exists, select
from sqlalchemy.orm import Session

from paperus.models import (
    Blob,
    Chunk,
    File,
    FileChunk,
    Import,
    ImportPart,
    Item,
    ItemChunk,
    Note,
    NoteChunk,
    Version,
)
from paperus.storage import BlobStore

log = logging.getLogger(__name__)


@dataclass
class Emptied:
    items: int = 0
    notes: int = 0
    files: int = 0
    """Files in the trash of papers that stay."""
    blobs: int = 0
    """Stored contents removed because nothing used them any more."""
    bytes: int = 0


def empty(
    db: Session,
    blobs: BlobStore,
    *,
    before: datetime | None = None,
    libraries: list[uuid.UUID] | None = None,
) -> Emptied:
    """Delete for good what went to the trash before ``before`` (everything
    in the trash if None), in these libraries (all if None); then remove
    stored contents and passages nothing refers to. Commits."""
    done = Emptied()

    def gone(model: type[Item] | type[Note]) -> list[ColumnElement[bool]]:
        conditions = [model.deleted_at.is_not(None)]
        if before is not None:
            conditions.append(model.deleted_at < before)
        if libraries is not None:
            conditions.append(model.library_id.in_(libraries))
        return conditions

    done.items = _count(db.execute(delete(Item).where(*gone(Item))))
    done.notes = _count(db.execute(delete(Note).where(*gone(Note))))
    in_libraries = select(Version.id).join(Item, Item.id == Version.item_id)
    if libraries is not None:
        in_libraries = in_libraries.where(Item.library_id.in_(libraries))
    file_conditions = [File.deleted_at.is_not(None), File.version_id.in_(in_libraries)]
    if before is not None:
        file_conditions.append(File.deleted_at < before)
    done.files = _count(db.execute(delete(File).where(*file_conditions)))
    db.commit()
    unused = collect_garbage(db, blobs)
    done.blobs, done.bytes = unused
    return done


def _count(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


def collect_garbage(db: Session, blobs: BlobStore) -> tuple[int, int]:
    """Remove stored contents no file or waiting import uses, and passages no
    file, note or paper's details use (with their vectors); returns
    (contents, bytes)."""
    orphans = db.execute(
        select(Blob.sha256, Blob.size).where(
            ~exists().where(File.blob_sha256 == Blob.sha256),
            ~exists().where(Import.blob_sha256 == Blob.sha256),
            ~exists().where(ImportPart.blob_sha256 == Blob.sha256),
        )
    ).all()
    for sha256, _ in orphans:
        db.execute(delete(Blob).where(Blob.sha256 == sha256))
    db.execute(
        delete(Chunk).where(
            ~exists().where(FileChunk.chunk_sha256 == Chunk.sha256),
            ~exists().where(NoteChunk.chunk_sha256 == Chunk.sha256),
            ~exists().where(ItemChunk.chunk_sha256 == Chunk.sha256),
        )
    )
    db.commit()
    # After the commit: a crash in between leaves files without a row (found
    # by an integrity check), never a row without its file.
    for sha256, _ in orphans:
        try:
            blobs.delete(sha256)
        except Exception:
            log.warning(
                "could not delete stored contents %s", sha256.hex(), exc_info=True
            )
    return len(orphans), sum(size or 0 for _, size in orphans)
