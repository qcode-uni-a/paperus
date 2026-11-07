"""Tags and collections: the rules shared by the API and other clients."""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from paperus.models import (
    Authorship,
    Collection,
    CollectionItem,
    Item,
    ItemTag,
    Library,
    Tag,
    TagSource,
)


class Rules(BaseModel):
    """What a smart collection holds: the papers matching every rule given
    (none given: all papers)."""

    tags_all: list[uuid.UUID] = []
    """With all of these tags."""
    tags_any: list[uuid.UUID] = []
    """With at least one of these tags."""
    tags_none: list[uuid.UUID] = []
    """With none of these tags."""
    types: list[str] = []
    """Of one of these types (CSL: article-journal, book, …)."""
    published_from: date | None = None
    published_to: date | None = None
    """Published between these days (both included). A paper whose date
    is known only to the month or year counts if that month or year
    touches the range."""
    year_from: int | None = Field(None, ge=0, le=9999)
    year_to: int | None = Field(None, ge=0, le=9999)
    """Published in these years (both included); older rules, the same as
    the dates 1 January and 31 December."""
    owners: list[uuid.UUID] = []
    """Owned by one of these libraries (a person's or a group's). A group's
    smart collection holds only that group's papers anyway."""
    added_days: int | None = Field(None, ge=1, le=36500)
    """Added to paperus in the last so many days."""
    authors: list[uuid.UUID] = []
    """Written by one of these people (``paperus.authors``)."""


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


def find_tag(db: Session, library_id: uuid.UUID, name: str) -> Tag | None:
    """The library's tag of this name, in any case."""
    return db.scalar(
        select(Tag).where(
            Tag.library_id == library_id,
            func.lower(Tag.name) == clean_name(name).lower(),
        )
    )


def tag_item(
    db: Session,
    item: Item,
    name: str,
    *,
    library_id: uuid.UUID,
    source: TagSource = TagSource.MANUAL,
    user_id: uuid.UUID | None = None,
) -> Tag:
    """Put the library's tag of this name on an item, creating the tag if
    needed (no duplicates). Callers check that the library may tag the item
    (see ``Access.may_hold``)."""
    tag = find_tag(db, library_id, name)
    if tag is None:
        tag = Tag(library_id=library_id, name=clean_name(name), change=0)
        db.add(tag)
        db.flush()
    link = next((link for link in item.tag_links if link.tag_id == tag.id), None)
    if link is None:
        item.tag_links.append(
            ItemTag(tag_id=tag.id, tag=tag, source=source, added_by=user_id)
        )
    elif source == TagSource.MANUAL and link.source != TagSource.MANUAL:
        # Put on by hand: the person's own now (no longer automatic).
        link.source = TagSource.MANUAL
    return tag


def untag_item(item: Item, tag_id: uuid.UUID) -> None:
    item.tag_links = [link for link in item.tag_links if link.tag_id != tag_id]


def merge_tags(db: Session, source: Tag, target: Tag) -> int:
    """One tag instead of two of the same meaning: ``target`` goes on every
    paper ``source`` is on, then ``source`` is deleted; how many papers it
    went on. Callers check that both are the person's to change."""
    added = 0
    for item in db.scalars(
        select(Item).join(ItemTag).where(ItemTag.tag_id == source.id)
    ).unique():
        old = next(link for link in item.tag_links if link.tag_id == source.id)
        if not any(link.tag_id == target.id for link in item.tag_links):
            item.tag_links.append(
                ItemTag(
                    tag_id=target.id,
                    tag=target,
                    source=old.source,
                    added_by=old.added_by,
                )
            )
            added += 1
        untag_item(item, source.id)
    db.delete(source)
    return added


def rename_tag(db: Session, tag: Tag, name: str) -> None:
    other = find_tag(db, tag.library_id, name)
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
    """Move under another collection of the same library (or to the top);
    never into itself."""
    if parent_id is not None:
        parent = db.get(Collection, parent_id)
        if parent is None:
            raise NotFound("parent collection not found")
        if parent.library_id != collection.library_id:
            raise Conflict("collections nest only within one library")
        if parent.rules is not None:
            raise Conflict("a smart collection holds no other collections")
        if parent_id in descendants(db, collection.id):
            raise Conflict("a collection cannot move into itself or below itself")
    collection.parent_id = parent_id


def move_to_library(
    db: Session,
    collection: Collection,
    library_id: uuid.UUID,
    may_hold: Callable[[Item], bool],
) -> int:
    """Give a collection and everything inside it to another library, at its
    top level. Items the new library's collections may not hold leave them
    (the items themselves stay where they are); returns how many links
    went."""
    ids = descendants(db, collection.id)
    for member in db.scalars(select(Collection).where(Collection.id.in_(ids))):
        member.library_id = library_id
    collection.parent_id = None
    removed = 0
    for item in db.scalars(
        select(Item).join(CollectionItem).where(CollectionItem.collection_id.in_(ids))
    ).unique():
        if may_hold(item):
            continue
        before = len(item.collection_links)
        item.collection_links = [
            link for link in item.collection_links if link.collection_id not in ids
        ]
        removed += before - len(item.collection_links)
    return removed


def add_to_collection(
    db: Session,
    collection: Collection,
    item_ids: list[uuid.UUID],
    user_id: uuid.UUID | None,
    may_hold: Callable[[Item], bool] = lambda item: True,
) -> int:
    """Add items (unknown or present ones, and those ``may_hold`` refuses,
    are skipped); returns how many."""
    added = 0
    for item_id in dict.fromkeys(item_ids):
        item = db.get(Item, item_id)
        if item is None or not may_hold(item):
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
    """Ids of items in the collection (and below it if ``nested``); for a
    smart collection, those matching its rules. Smart collections inside
    another one add nothing to it (they are saved searches, kept there)."""
    collection = db.get(Collection, collection_id)
    if collection is not None and collection.rules is not None:
        return select(Item.id).where(*matching(db, collection))
    ids = descendants(db, collection_id) if nested else [collection_id]
    return select(CollectionItem.item_id).where(CollectionItem.collection_id.in_(ids))


def published_between(rules: Rules) -> tuple[date | None, date | None]:
    """The first and last day of the rules' publication range (years as
    from 1 January to 31 December); None where open."""
    start = rules.published_from or (
        date(rules.year_from, 1, 1) if rules.year_from else None
    )
    end = rules.published_to or (date(rules.year_to, 12, 31) if rules.year_to else None)
    return start, end


def matching(db: Session, collection: Collection) -> list[ColumnElement[bool]]:
    """Conditions on items for a smart collection's rules (who may see
    which item is up to the caller)."""
    conditions = rule_conditions(Rules.model_validate(collection.rules or {}))
    owner = collection.library_id
    group = db.scalar(select(Library.group_id).where(Library.id == owner))
    if group is not None:
        conditions.append(Item.library_id == collection.library_id)
    return conditions


def rule_conditions(rules: Rules) -> list[ColumnElement[bool]]:
    """Conditions on items for these rules (a smart collection's, or the
    library's filter)."""

    def tagged(tag_ids: list[uuid.UUID]) -> Select[uuid.UUID]:
        return select(ItemTag.item_id).where(ItemTag.tag_id.in_(tag_ids))

    conditions: list[ColumnElement[bool]] = [
        Item.id.in_(tagged([tag_id])) for tag_id in rules.tags_all
    ]
    if rules.tags_any:
        conditions.append(Item.id.in_(tagged(rules.tags_any)))
    if rules.tags_none:
        conditions.append(Item.id.not_in(tagged(rules.tags_none)))
    if rules.types:
        conditions.append(Item.type.in_(rules.types))
    start, end = published_between(rules)
    if start is not None:
        conditions.append(Item.issued_to >= start)
    if end is not None:
        conditions.append(Item.issued_from <= end)
    if rules.owners:
        conditions.append(Item.library_id.in_(rules.owners))
    if rules.authors:
        conditions.append(
            Item.id.in_(
                select(Authorship.item_id).where(
                    Authorship.author_id.in_(rules.authors)
                )
            )
        )
    if rules.added_days is not None:
        since = datetime.now(UTC) - timedelta(days=rules.added_days)
        conditions.append(Item.created_at >= since)
    return conditions


def make_smart(db: Session, collection: Collection, rules: Rules | None) -> None:
    """Give a collection rules (or take them away: an empty collection to
    add papers to). Only an empty collection becomes smart: the papers in it
    would be hidden."""
    if rules is not None and collection.rules is None:
        has_items = db.scalar(
            select(CollectionItem.item_id)
            .where(CollectionItem.collection_id == collection.id)
            .limit(1)
        )
        has_children = db.scalar(
            select(Collection.id).where(Collection.parent_id == collection.id).limit(1)
        )
        if has_items is not None or has_children is not None:
            raise Conflict(
                "only an empty collection without collections inside can become "
                "a smart collection"
            )
    collection.rules = rules.model_dump(mode="json") if rules is not None else None
