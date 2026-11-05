"""Handing a person's private things to a group or another person, e.g.
when they leave (Administration → Settings → Users)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from paperus import organize
from paperus.library import set_owner
from paperus.models import (
    Collection,
    CollectionItem,
    CollectionNote,
    Item,
    ItemTag,
    Library,
    Note,
    Tag,
)


@dataclass
class Private:
    """What a person's own library holds (the trash included)."""

    items: int = 0
    notes: int = 0
    tags: int = 0
    collections: int = 0


def private(db: Session, library_id: uuid.UUID) -> Private:
    def count(model: type[Item | Note | Tag | Collection]) -> int:
        query = select(func.count()).where(model.library_id == library_id)
        return db.scalar(query) or 0

    return Private(
        items=count(Item),
        notes=count(Note),
        tags=count(Tag),
        collections=count(Collection),
    )


def hand_over(db: Session, source: uuid.UUID, target: uuid.UUID) -> Private:
    """Give everything in the library ``source`` to ``target``: papers,
    notes, collections (with what is in them, as far as the new owner's
    collections may hold it) and tags (merged with the new owner's tags of
    the same name). Returns what went. Does not commit."""
    moved = private(db, source)
    to_group = (
        db.scalar(select(Library.group_id).where(Library.id == target)) is not None
    )
    for item in db.scalars(select(Item).where(Item.library_id == source)):
        set_owner(db, item, target)
    for note in db.scalars(select(Note).where(Note.library_id == source)):
        note.library_id = target
    db.flush()

    collections = list(
        db.scalars(select(Collection.id).where(Collection.library_id == source))
    )
    for collection in db.scalars(
        select(Collection).where(
            Collection.library_id == source, Collection.parent_id.is_(None)
        )
    ):
        organize.move_to_library(
            db,
            collection,
            target,
            # A group's collections hold only its own papers and notes.
            lambda item: not to_group or item.library_id == target,
        )
    if to_group and collections:
        foreign = select(Item.id).where(Item.library_id != target)
        db.execute(
            delete(CollectionItem).where(
                CollectionItem.collection_id.in_(collections),
                CollectionItem.item_id.in_(foreign),
            )
        )
        db.execute(
            delete(CollectionNote).where(
                CollectionNote.collection_id.in_(collections),
                CollectionNote.note_id.in_(
                    select(Note.id).where(Note.library_id != target)
                ),
            )
        )

    tags = list(db.scalars(select(Tag).where(Tag.library_id == source)))
    if to_group and tags:
        # A group's tags, too, are only on its own papers.
        db.execute(
            delete(ItemTag).where(
                ItemTag.tag_id.in_([tag.id for tag in tags]),
                ItemTag.item_id.in_(select(Item.id).where(Item.library_id != target)),
            )
        )
        db.expire_all()
    for tag in tags:
        same = organize.find_tag(db, target, tag.name)
        if same is None:
            tag.library_id = target
            continue
        tagged = select(ItemTag.item_id).where(ItemTag.tag_id == same.id)
        for link in db.scalars(
            select(ItemTag).where(
                ItemTag.tag_id == tag.id, ItemTag.item_id.not_in(tagged)
            )
        ):
            link.tag_id = same.id
        db.flush()
        db.delete(tag)
    db.flush()
    return moved
