"""A paper's details (title and abstract) as one search passage
(``ItemChunk``): search finds a paper by them, with or without a file, and
ranks such a match above one in some text. Kept current on every change of
an item's title or abstract, its versions or its manual edits (a hook on
the session, so every way of changing them counts); vectors for search by
meaning follow in the embedding sweep."""

import hashlib

from sqlalchemy import event, inspect
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, UOWTransaction

from paperus.abstracts import plain
from paperus.library import citation_csl
from paperus.models import Chunk, Item, ItemChunk, Version


def text_of(item: Item) -> str:
    """What is searched: the title, then the abstract the paper shows (its
    details' own, else one found for it), if any."""
    abstract = citation_csl(item).get("abstract")
    return "\n\n".join(
        part
        for part in (item.title, plain(str(abstract)) if abstract else None)
        if part
    )


def index(db: Session, item: Item) -> None:
    """Store the item's details passage (on the connection: also from within
    a flush)."""
    text = text_of(item)
    sha256 = hashlib.sha256(text.encode()).digest()
    connection = db.connection()
    connection.execute(
        insert(Chunk).values(sha256=sha256, text=text).on_conflict_do_nothing()
    )
    connection.execute(
        insert(ItemChunk)
        .values(item_id=item.id, chunk_sha256=sha256)
        .on_conflict_do_update(
            index_elements=[ItemChunk.item_id], set_={"chunk_sha256": sha256}
        )
    )


def _changed(item: Item) -> bool:
    state = inspect(item)
    return any(
        state.attrs[name].history.has_changes()
        for name in ("title", "abstract", "overrides")
    )


@event.listens_for(Session, "before_flush")
def _note_changes(db: Session, flush: UOWTransaction, instances: object) -> None:
    """Remember the items whose title or abstract may be new (indexed once
    they are written, when new ones have their ids): new or changed, or with
    a version added, changed or removed."""
    pending = db.info.setdefault("paperus_details", set())
    for obj in (*db.new, *db.dirty, *db.deleted):
        if isinstance(obj, Item) and (obj in db.new or _changed(obj)):
            pending.add(obj)
        elif isinstance(obj, Version) and obj.item is not None:
            pending.add(obj.item)


@event.listens_for(Session, "after_flush_postexec")
def _index_changes(db: Session, flush: UOWTransaction) -> None:
    pending = db.info.pop("paperus_details", set())
    with db.no_autoflush:
        for item in pending:
            if inspect(item).persistent and item.title:
                index(db, item)


@event.listens_for(Session, "after_rollback")
def _forget(db: Session) -> None:
    db.info.pop("paperus_details", None)
