"""Notes: saving text with an edit history, and passages for search.

See the Notes section of docs/architecture.md.
"""

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus.models import Chunk, Note, NoteChunk, NoteRevision
from paperus.text import chunk_document

# Saves by the same person within this time count as one change.
SESSION = timedelta(minutes=10)

_MARKS = re.compile(
    r"^\s{0,3}(#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)|[*_`~]|\[|\]\([^)]*\)"
)


def title_of(text: str) -> str:
    """The first non-empty line, without Markdown marks."""
    for line in text.splitlines():
        plain = _MARKS.sub("", line).strip()
        if plain:
            return plain[:300]
    return ""


class Conflict(Exception):
    """Someone saved the text since the editor read it."""


def etag(note: Note) -> str:
    """The text's version, for ``If-Match`` (and MCP's ``change``): it moves
    only when the text changes, not when the note is filed or linked."""
    return str(int(note.text_changed_at.timestamp() * 1_000_000))


def save(
    db: Session, note_id: uuid.UUID, text: str, expected: str, user_id: uuid.UUID | None
) -> Note:
    """Replace the text if it is still the version ``expected`` (from
    ``etag``); locks the note, so two saves from the same version cannot both
    pass. Raises ``Conflict`` otherwise. Callers check rights first."""
    note = db.get(Note, note_id, with_for_update=True, populate_existing=True)
    if note is None:
        raise LookupError(note_id)
    if etag(note) != expected:
        raise Conflict
    set_text(db, note, text, user_id)
    return note


def create(
    db: Session, library_id: uuid.UUID, text: str, user_id: uuid.UUID | None
) -> Note:
    now = datetime.now(UTC)
    note = Note(
        library_id=library_id,
        text=text,
        title=title_of(text),
        created_by=user_id,
        changed_by=user_id,
        text_changed_at=now,
    )
    db.add(note)
    db.flush()
    index(db, note)
    return note


def set_text(db: Session, note: Note, text: str, user_id: uuid.UUID | None) -> None:
    """Replace the text, keeping the previous one in the history unless the
    same person saved it within ``SESSION`` (one editing session)."""
    if text == note.text:
        return
    now = datetime.now(UTC)
    same_session = note.changed_by == user_id and now - note.text_changed_at < SESSION
    if not same_session and note.text:
        db.add(
            NoteRevision(
                note_id=note.id,
                text=note.text,
                written_by=note.changed_by,
                written_at=note.text_changed_at,
            )
        )
    note.text = text
    note.title = title_of(text)
    note.changed_by = user_id
    note.text_changed_at = now
    index(db, note)


def index(db: Session, note: Note) -> None:
    """Split the text into passages for search (vectors follow in a job)."""
    db.execute(delete(NoteChunk).where(NoteChunk.note_id == note.id))
    for position, chunk in enumerate(chunk_document(note.text)):
        sha256 = hashlib.sha256(chunk.text.encode()).digest()
        db.execute(
            insert(Chunk)
            .values(sha256=sha256, text=chunk.text)
            .on_conflict_do_nothing()
        )
        db.add(NoteChunk(note_id=note.id, position=position, chunk_sha256=sha256))
