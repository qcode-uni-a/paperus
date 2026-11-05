"""Tags and collections."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from paperus import organize
from paperus.api.deps import DB, CurrentUser
from paperus.models import Collection, CollectionItem, Item, ItemTag, Tag, TagSource

router = APIRouter(tags=["organize"])

Name = Annotated[str, Field(min_length=1, max_length=200)]


class TagOut(BaseModel):
    id: uuid.UUID
    name: str
    count: int
    """Items with this tag (not in the trash)."""


class ItemTagOut(BaseModel):
    id: uuid.UUID
    name: str
    source: TagSource


class TagIn(BaseModel):
    name: Name


class ItemPreview(BaseModel):
    id: uuid.UUID
    title: str


class CollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    parent_id: uuid.UUID | None
    count: int
    """Items directly in this collection (not in the trash)."""
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
                id=link.tag.id, name=link.tag.name, source=TagSource(link.source)
            )
            for link in item.tag_links
        ),
        key=lambda tag: tag.name.lower(),
    )


# Tags


@router.get("/api/tags")
def list_tags(db: DB, user: CurrentUser) -> list[TagOut]:
    counts = (
        select(ItemTag.tag_id, func.count().label("count"))
        .join(Item, Item.id == ItemTag.item_id)
        .where(Item.deleted_at.is_(None))
        .group_by(ItemTag.tag_id)
        .subquery()
    )
    rows = db.execute(
        select(Tag, func.coalesce(counts.c.count, 0))
        .outerjoin(counts, counts.c.tag_id == Tag.id)
        .order_by(func.lower(Tag.name))
    )
    return [TagOut(id=tag.id, name=tag.name, count=count) for tag, count in rows]


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
def rename_tag(tag_id: uuid.UUID, body: TagIn, db: DB, user: CurrentUser) -> TagOut:
    """Rename a tag everywhere (409 if another tag has that name)."""
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(404, "tag not found")
    try:
        organize.rename_tag(db, tag, body.name)
    except organize.Conflict as error:
        raise HTTPException(409, str(error)) from error
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
    count = db.scalar(
        select(func.count())
        .select_from(CollectionItem)
        .join(Item, Item.id == CollectionItem.item_id)
        .where(CollectionItem.collection_id == collection.id, Item.deleted_at.is_(None))
    )
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        parent_id=collection.parent_id,
        count=count or 0,
    )


@router.get("/api/collections")
def list_collections(db: DB, user: CurrentUser) -> list[CollectionOut]:
    """All collections, flat; ``parent_id`` gives the tree."""
    counts = (
        select(CollectionItem.collection_id, func.count().label("count"))
        .join(Item, Item.id == CollectionItem.item_id)
        .where(Item.deleted_at.is_(None))
        .group_by(CollectionItem.collection_id)
        .subquery()
    )
    rows = db.execute(
        select(Collection, func.coalesce(counts.c.count, 0))
        .outerjoin(counts, counts.c.collection_id == Collection.id)
        .order_by(func.lower(Collection.name))
    )
    recent = _recent_items(db)
    return [
        CollectionOut(
            id=c.id,
            name=c.name,
            description=c.description,
            parent_id=c.parent_id,
            count=count,
            recent=recent.get(c.id, []),
        )
        for c, count in rows
    ]


def _recent_items(
    db: DB, per_collection: int = 3
) -> dict[uuid.UUID, list[ItemPreview]]:
    """The last items added to each collection, newest first."""
    ranked = (
        select(
            CollectionItem.collection_id,
            Item.id,
            Item.title,
            func.row_number()
            .over(
                partition_by=CollectionItem.collection_id,
                order_by=CollectionItem.created_at.desc(),
            )
            .label("rank"),
        )
        .join(Item, Item.id == CollectionItem.item_id)
        .where(Item.deleted_at.is_(None))
        .subquery()
    )
    previews: dict[uuid.UUID, list[ItemPreview]] = {}
    for collection_id, item_id, title, _ in db.execute(
        select(ranked).where(ranked.c.rank <= per_collection).order_by(ranked.c.rank)
    ):
        previews.setdefault(collection_id, []).append(
            ItemPreview(id=item_id, title=title)
        )
    return previews


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
