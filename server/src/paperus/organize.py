"""Tags and collections: the rules shared by the API and other clients."""

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from paperus.models import Collection, CollectionItem, Item, ItemTag, Tag, TagSource


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


def clean_name(name: str) -> str:
    """Single spaces, no surrounding space; empty names are not allowed."""
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValueError("name must not be empty")
    return cleaned


def find_tag(db: Session, name: str) -> Tag | None:
    return db.scalar(
        select(Tag).where(func.lower(Tag.name) == clean_name(name).lower())
    )


def tag_item(
    db: Session,
    item: Item,
    name: str,
    *,
    source: TagSource = TagSource.MANUAL,
    user_id: uuid.UUID | None = None,
) -> Tag:
    """Put a tag on an item, creating the tag if needed (no duplicates)."""
    tag = find_tag(db, name)
    if tag is None:
        tag = Tag(name=clean_name(name), change=0)
        db.add(tag)
        db.flush()
    if not any(link.tag_id == tag.id for link in item.tag_links):
        item.tag_links.append(
            ItemTag(tag_id=tag.id, tag=tag, source=source, added_by=user_id)
        )
    return tag


def untag_item(item: Item, tag_id: uuid.UUID) -> None:
    item.tag_links = [link for link in item.tag_links if link.tag_id != tag_id]


def rename_tag(db: Session, tag: Tag, name: str) -> None:
    other = find_tag(db, name)
    if other is not None and other.id != tag.id:
        raise Conflict(f"a tag {other.name!r} exists already")
    tag.name = clean_name(name)


def descendants(db: Session, collection_id: uuid.UUID) -> list[uuid.UUID]:
    """The collection and all collections below it."""
    tree = (
        select(Collection.id)
        .where(Collection.id == collection_id)
        .cte("tree", recursive=True)
    )
    tree = tree.union_all(
        select(Collection.id).where(Collection.parent_id == tree.c.id)
    )
    return list(db.scalars(select(tree.c.id)))


def move_collection(
    db: Session, collection: Collection, parent_id: uuid.UUID | None
) -> None:
    """Move under another collection (or to the top); never into itself."""
    if parent_id is not None:
        if db.get(Collection, parent_id) is None:
            raise NotFound("parent collection not found")
        if parent_id in descendants(db, collection.id):
            raise Conflict("a collection cannot move into itself or below itself")
    collection.parent_id = parent_id


def add_to_collection(
    db: Session,
    collection: Collection,
    item_ids: list[uuid.UUID],
    user_id: uuid.UUID | None,
) -> int:
    """Add items (unknown or present ones are skipped); returns how many."""
    added = 0
    for item_id in dict.fromkeys(item_ids):
        item = db.get(Item, item_id)
        if item is None:
            continue
        if any(link.collection_id == collection.id for link in item.collection_links):
            continue
        item.collection_links.append(
            CollectionItem(collection_id=collection.id, added_by=user_id)
        )
        added += 1
    return added


def item_ids_in(
    db: Session, collection_id: uuid.UUID, *, nested: bool
) -> Select[uuid.UUID]:
    """Ids of items in the collection (and below it if ``nested``)."""
    ids = descendants(db, collection_id) if nested else [collection_id]
    return select(CollectionItem.item_id).where(CollectionItem.collection_id.in_(ids))
