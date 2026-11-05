"""Tags and collections."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from paperus import organize
from paperus.api.deps import DB, CurrentUser
from paperus.models import (
    Collection,
    CollectionItem,
    Item,
    ItemTag,
    Tag,
    TagColor,
    TagSource,
)

router = APIRouter(tags=["organize"])

Name = Annotated[str, Field(min_length=1, max_length=200)]


class TagOut(BaseModel):
    id: uuid.UUID
    name: str
    color: TagColor | None
    description: str | None
    count: int
    """Items with this tag (not in the trash)."""
    sources: dict[TagSource, int]
    """Of those, how many were tagged by hand, automatically or by AI."""
    created_at: datetime
    last_used: datetime | None
    """When the tag was last put on an item."""


class ItemTagOut(BaseModel):
    id: uuid.UUID
    name: str
    color: TagColor | None
    source: TagSource


class TagIn(BaseModel):
    name: Name


class TagChange(BaseModel):
    """Only the fields given are changed; ``null`` clears colour or description."""

    name: Name | None = None
    color: TagColor | None = None
    description: Annotated[str | None, Field(max_length=2000)] = None


class ItemPreview(BaseModel):
    id: uuid.UUID
    title: str


class CollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    parent_id: uuid.UUID | None
    count: int
    """Items in this collection or the collections inside (not in the trash)."""
    direct: int = 0
    """Of those, the items directly in this collection."""
    recent: list[ItemPreview] = []
    """The last items added (up to three), for previews."""


class CollectionIn(BaseModel):
    name: Name
    description: str | None = None
    parent_id: uuid.UUID | None = None


class CollectionChange(BaseModel):
    """Only the fields given are changed; ``parent_id: null`` moves to the top."""

    name: Name | None = None
    description: str | None = None
    parent_id: uuid.UUID | None = None


class ItemIds(BaseModel):
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


def _item(db: DB, item_id: uuid.UUID) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    return item


def _collection(db: DB, collection_id: uuid.UUID) -> Collection:
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(404, "collection not found")
    return collection


def item_tags(item: Item) -> list[ItemTagOut]:
    return sorted(
        (
            ItemTagOut(
                id=link.tag.id,
                name=link.tag.name,
                color=_color(link.tag),
                source=TagSource(link.source),
            )
            for link in item.tag_links
        ),
        key=lambda tag: tag.name.lower(),
    )


# Tags


def _color(tag: Tag) -> TagColor | None:
    return TagColor(tag.color) if tag.color in set(TagColor) else None


@router.get("/api/tags")
def list_tags(db: DB, user: CurrentUser) -> list[TagOut]:
    """All tags with how they are used (items in the trash do not count)."""
    usage = db.execute(
        select(
            ItemTag.tag_id, ItemTag.source, func.count(), func.max(ItemTag.created_at)
        )
        .join(Item, Item.id == ItemTag.item_id)
        .where(Item.deleted_at.is_(None))
        .group_by(ItemTag.tag_id, ItemTag.source)
    )
    sources: dict[uuid.UUID, dict[TagSource, int]] = {}
    last_used: dict[uuid.UUID, datetime] = {}
    for tag_id, source, count, last in usage:
        sources.setdefault(tag_id, {})[TagSource(source)] = count
        if tag_id not in last_used or last > last_used[tag_id]:
            last_used[tag_id] = last
    tags = db.scalars(select(Tag).order_by(func.lower(Tag.name)))
    return [
        TagOut(
            id=tag.id,
            name=tag.name,
            color=_color(tag),
            description=tag.description,
            count=sum(sources.get(tag.id, {}).values()),
            sources=sources.get(tag.id, {}),
            created_at=tag.created_at,
            last_used=last_used.get(tag.id),
        )
        for tag in tags
    ]


class TagNew(BaseModel):
    name: Name
    color: TagColor | None = None
    description: Annotated[str | None, Field(max_length=2000)] = None


@router.post("/api/tags", status_code=201)
def create_tag(body: TagNew, db: DB, user: CurrentUser) -> TagOut:
    """A tag not on any item yet (409 if one with that name exists)."""
    if organize.find_tag(db, body.name) is not None:
        raise HTTPException(409, f"a tag {body.name.strip()!r} exists already")
    try:
        name = organize.clean_name(body.name)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    tag = Tag(
        name=name,
        color=body.color,
        description=(body.description or "").strip() or None,
        change=0,
    )
    db.add(tag)
    db.commit()
    return next(t for t in list_tags(db, user) if t.id == tag.id)


@router.post("/api/items/{item_id}/tags", status_code=201)
def add_tag(
    item_id: uuid.UUID, body: TagIn, db: DB, user: CurrentUser
) -> list[ItemTagOut]:
    """Tag an item; the tag is created if it does not exist (any case)."""
    item = _item(db, item_id)
    try:
        organize.tag_item(db, item, body.name, user_id=user.id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    db.commit()
    return item_tags(item)


@router.delete("/api/items/{item_id}/tags/{tag_id}")
def remove_tag(
    item_id: uuid.UUID, tag_id: uuid.UUID, db: DB, user: CurrentUser
) -> list[ItemTagOut]:
    item = _item(db, item_id)
    organize.untag_item(item, tag_id)
    db.commit()
    return item_tags(item)


@router.patch("/api/tags/{tag_id}")
def change_tag(tag_id: uuid.UUID, body: TagChange, db: DB, user: CurrentUser) -> TagOut:
    """Rename a tag everywhere (409 if another tag has that name), or set its
    colour or description."""
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(404, "tag not found")
    if body.name is not None:
        try:
            organize.rename_tag(db, tag, body.name)
        except organize.Conflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    if "color" in body.model_fields_set:
        tag.color = body.color
    if "description" in body.model_fields_set:
        tag.description = (body.description or "").strip() or None
    db.commit()
    return next(t for t in list_tags(db, user) if t.id == tag.id)


@router.delete("/api/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: uuid.UUID, db: DB, user: CurrentUser) -> Response:
    """Remove a tag from every item and delete it."""
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(404, "tag not found")
    for item in db.scalars(select(Item).join(ItemTag).where(ItemTag.tag_id == tag_id)):
        organize.untag_item(item, tag_id)
    db.delete(tag)
    db.commit()
    return Response(status_code=204)


# Collections


def _collection_out(db: DB, collection: Collection) -> CollectionOut:
    count, recent = _contents(db, collection.id).get(collection.id, (0, []))
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        parent_id=collection.parent_id,
        count=count,
        direct=_direct_counts(db, collection.id).get(collection.id, 0),
        recent=recent,
    )


def _direct_counts(db: DB, only: uuid.UUID | None = None) -> dict[uuid.UUID, int]:
    query = (
        select(CollectionItem.collection_id, func.count())
        .join(Item, Item.id == CollectionItem.item_id)
        .where(Item.deleted_at.is_(None))
        .group_by(CollectionItem.collection_id)
    )
    if only is not None:
        query = query.where(CollectionItem.collection_id == only)
    return {collection_id: count for collection_id, count in db.execute(query)}


@router.get("/api/collections")
def list_collections(db: DB, user: CurrentUser) -> list[CollectionOut]:
    """All collections, flat; ``parent_id`` gives the tree."""
    contents = _contents(db)
    direct = _direct_counts(db)
    collections = db.scalars(select(Collection).order_by(func.lower(Collection.name)))
    return [
        CollectionOut(
            id=c.id,
            name=c.name,
            description=c.description,
            parent_id=c.parent_id,
            count=contents.get(c.id, (0, []))[0],
            direct=direct.get(c.id, 0),
            recent=contents.get(c.id, (0, []))[1],
        )
        for c in collections
    ]


def _contents(
    db: DB, root: uuid.UUID | None = None, per_collection: int = 3
) -> dict[uuid.UUID, tuple[int, list[ItemPreview]]]:
    """Per collection, its items including those of the collections inside:
    how many, and the last added (newest first). Only ``root`` if given."""
    start = select(Collection.id.label("root"), Collection.id.label("member"))
    if root is not None:
        start = start.where(Collection.id == root)
    tree = start.cte("tree", recursive=True)
    tree = tree.union_all(
        select(tree.c.root, Collection.id).where(Collection.parent_id == tree.c.member)
    )
    # An item in several collections of one tree counts once, as last added.
    items = (
        select(
            tree.c.root,
            CollectionItem.item_id,
            func.max(CollectionItem.created_at).label("added"),
        )
        .join(CollectionItem, CollectionItem.collection_id == tree.c.member)
        .join(Item, Item.id == CollectionItem.item_id)
        .where(Item.deleted_at.is_(None))
        .group_by(tree.c.root, CollectionItem.item_id)
        .subquery()
    )
    ranked = (
        select(
            items.c.root,
            Item.id,
            Item.title,
            func.row_number()
            .over(partition_by=items.c.root, order_by=items.c.added.desc())
            .label("rank"),
            func.count().over(partition_by=items.c.root).label("count"),
        )
        .join(Item, Item.id == items.c.item_id)
        .subquery()
    )
    contents: dict[uuid.UUID, tuple[int, list[ItemPreview]]] = {}
    for collection_id, item_id, title, _, count in db.execute(
        select(ranked).where(ranked.c.rank <= per_collection).order_by(ranked.c.rank)
    ):
        _, previews = contents.setdefault(collection_id, (count, []))
        previews.append(ItemPreview(id=item_id, title=title))
    return contents


@router.post("/api/collections", status_code=201)
def create_collection(body: CollectionIn, db: DB, user: CurrentUser) -> CollectionOut:
    try:
        name = organize.clean_name(body.name)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if body.parent_id is not None:
        _collection(db, body.parent_id)
    collection = Collection(
        name=name,
        description=body.description,
        parent_id=body.parent_id,
        created_by=user.id,
        change=0,
    )
    db.add(collection)
    db.commit()
    return _collection_out(db, collection)


@router.patch("/api/collections/{collection_id}")
def change_collection(
    collection_id: uuid.UUID, body: CollectionChange, db: DB, user: CurrentUser
) -> CollectionOut:
    """Rename, describe or move a collection (not into itself)."""
    collection = _collection(db, collection_id)
    given = body.model_fields_set
    try:
        if "name" in given and body.name is not None:
            collection.name = organize.clean_name(body.name)
        if "description" in given:
            collection.description = body.description
        if "parent_id" in given:
            organize.move_collection(db, collection, body.parent_id)
    except organize.NotFound as error:
        raise HTTPException(404, str(error)) from error
    except organize.Conflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    db.commit()
    return _collection_out(db, collection)


@router.delete("/api/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: uuid.UUID, db: DB, user: CurrentUser) -> Response:
    """Delete a collection and its subcollections; items stay in the library."""
    collection = _collection(db, collection_id)
    ids = organize.descendants(db, collection.id)
    # Their items change (fewer collections), which sync clients should see.
    for item in db.scalars(
        select(Item).join(CollectionItem).where(CollectionItem.collection_id.in_(ids))
    ).unique():
        item.collection_links = [
            link for link in item.collection_links if link.collection_id not in ids
        ]
    # Links first, before the database's cascade removes them under the ORM.
    db.flush()
    db.delete(collection)
    db.commit()
    return Response(status_code=204)


@router.post("/api/collections/{collection_id}/items")
def add_items(
    collection_id: uuid.UUID, body: ItemIds, db: DB, user: CurrentUser
) -> CollectionOut:
    collection = _collection(db, collection_id)
    organize.add_to_collection(db, collection, body.item_ids, user.id)
    db.commit()
    return _collection_out(db, collection)


@router.delete("/api/collections/{collection_id}/items/{item_id}")
def remove_item(
    collection_id: uuid.UUID, item_id: uuid.UUID, db: DB, user: CurrentUser
) -> CollectionOut:
    collection = _collection(db, collection_id)
    item = _item(db, item_id)
    item.collection_links = [
        link for link in item.collection_links if link.collection_id != collection_id
    ]
    db.commit()
    return _collection_out(db, collection)
