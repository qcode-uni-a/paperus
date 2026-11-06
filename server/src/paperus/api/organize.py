"""Tags and collections."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from paperus import library, organize
from paperus.access import Access, Forbidden
from paperus.api.deps import DB, CurrentAccess
from paperus.models import (
    Collection,
    CollectionItem,
    Item,
    ItemTag,
    PinnedCollection,
    Tag,
    TagColor,
    TagSource,
)

router = APIRouter(tags=["organize"])

Name = Annotated[str, Field(min_length=1, max_length=200)]


class TagOut(BaseModel):
    id: uuid.UUID
    library_id: uuid.UUID
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
    library_id: uuid.UUID | None = None
    """Whose tag: the item's owner (for members of its group) or the person's
    own (a private tag). Default: the item's owner if the person may change
    it, else their own."""


class TagChange(BaseModel):
    """Only the fields given are changed; ``null`` clears colour or description."""

    name: Name | None = None
    color: TagColor | None = None
    description: Annotated[str | None, Field(max_length=2000)] = None
    library_id: uuid.UUID | None = None
    """A new owner the person may change (the tag stays on all its papers)."""


class ItemPreview(BaseModel):
    id: uuid.UUID
    title: str


class CollectionOut(BaseModel):
    id: uuid.UUID
    library_id: uuid.UUID
    name: str
    description: str | None
    parent_id: uuid.UUID | None
    count: int
    """Items in this collection or the collections inside (not in the trash)."""
    direct: int = 0
    """Of those, the items directly in this collection."""
    recent: list[ItemPreview] = []
    """The last items added (up to three), for previews."""
    pinned: bool = False
    """The person pinned it to their sidebar."""
    rules: organize.Rules | None = None
    """A smart collection: it holds the papers matching these rules (papers
    cannot be added to it, and it holds no collections)."""


class CollectionIn(BaseModel):
    name: Name
    description: str | None = None
    parent_id: uuid.UUID | None = None
    library_id: uuid.UUID | None = None
    """The parent's library if inside another collection, else the person's
    default library if not given."""
    rules: organize.Rules | None = None
    """Given: a smart collection."""


class CollectionChange(BaseModel):
    """Only the fields given are changed; ``parent_id: null`` moves to the top.

    ``library_id`` gives the collection, with the collections inside it, to
    another library the person may change, e.g. from their own to a group
    or back (members may delete a group's collections anyway). It lands at
    the top level there unless ``parent_id`` names a collection there.
    Papers a group's collection may not hold leave it, unless
    ``add_papers`` puts them into the group.
    """

    name: Name | None = None
    description: str | None = None
    parent_id: uuid.UUID | None = None
    library_id: uuid.UUID | None = None
    add_papers: bool = False
    """On a move into a group: give the papers the group does not own yet to
    the group (those the person may change) instead of leaving them out."""
    rules: organize.Rules | None = None
    """New rules of a smart collection; given on an empty collection, it
    becomes one; ``null`` turns a smart collection into an empty one."""


class MovePreview(BaseModel):
    """What moving a collection (with those inside) into a library does."""

    papers: int
    """Papers in the collections the person can read."""
    not_in_library: int
    """Of those, papers the target does not own: with ``add_papers`` they
    become its papers (if the person may change them), else they leave the
    collections."""


class CollectionChanged(CollectionOut):
    left_out: int = 0
    """Papers that left the collections on a move to another library."""


class ItemIds(BaseModel):
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


def _item(db: DB, access: Access, item_id: uuid.UUID) -> Item:
    item = db.get(Item, item_id)
    if item is None or not access.can_read_item(item):
        raise HTTPException(404, "item not found")
    return item


def _collection(
    db: DB, access: Access, collection_id: uuid.UUID, *, write: bool = False
) -> Collection:
    collection = db.get(Collection, collection_id)
    if collection is None or not access.can_read(collection.library_id):
        raise HTTPException(404, "collection not found")
    if write:
        access.require_write(collection.library_id)
    return collection


def _not_smart(collection: Collection) -> None:
    if collection.rules is not None:
        raise HTTPException(
            409, "a smart collection finds its papers by its rules; change those"
        )


def _tag(db: DB, access: Access, tag_id: uuid.UUID, *, write: bool = False) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None or not access.can_read(tag.library_id):
        raise HTTPException(404, "tag not found")
    if write:
        access.require_write(tag.library_id)
    return tag


def item_tags(item: Item, access: Access) -> list[ItemTagOut]:
    return sorted(
        (
            ItemTagOut(
                id=link.tag.id,
                name=link.tag.name,
                color=_color(link.tag),
                source=TagSource(link.source),
            )
            for link in item.tag_links
            if access.can_read(link.tag.library_id)
        ),
        key=lambda tag: tag.name.lower(),
    )


# Tags


def _color(tag: Tag) -> TagColor | None:
    return TagColor(tag.color) if tag.color in set(TagColor) else None


@router.get("/api/tags")
def list_tags(db: DB, access: CurrentAccess) -> list[TagOut]:
    """The tags of the libraries the person can read, with how they are used
    (items in the trash do not count)."""
    usage = db.execute(
        select(
            ItemTag.tag_id, ItemTag.source, func.count(), func.max(ItemTag.created_at)
        )
        .join(Item, Item.id == ItemTag.item_id)
        .where(Item.deleted_at.is_(None), access.item_filter())
        .group_by(ItemTag.tag_id, ItemTag.source)
    )
    sources: dict[uuid.UUID, dict[TagSource, int]] = {}
    last_used: dict[uuid.UUID, datetime] = {}
    for tag_id, source, count, last in usage:
        sources.setdefault(tag_id, {})[TagSource(source)] = count
        if tag_id not in last_used or last > last_used[tag_id]:
            last_used[tag_id] = last
    tags = db.scalars(
        select(Tag)
        .where(Tag.library_id.in_(access.readable))
        .order_by(func.lower(Tag.name))
    )
    return [
        TagOut(
            id=tag.id,
            library_id=tag.library_id,
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
    library_id: uuid.UUID | None = None
    """The person's default library if not given."""


@router.post("/api/tags", status_code=201)
def create_tag(body: TagNew, db: DB, access: CurrentAccess) -> TagOut:
    """A tag not on any item yet (409 if the library has one of that name)."""
    library_id = access.target_library(body.library_id)
    try:
        name = organize.clean_name(body.name)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if organize.find_tag(db, library_id, name) is not None:
        raise HTTPException(409, f"a tag {name!r} exists already")
    tag = Tag(
        library_id=library_id,
        name=name,
        color=body.color,
        description=(body.description or "").strip() or None,
        change=0,
    )
    db.add(tag)
    db.commit()
    return next(t for t in list_tags(db, access) if t.id == tag.id)


@router.post("/api/items/{item_id}/tags", status_code=201)
def add_tag(
    item_id: uuid.UUID, body: TagIn, db: DB, access: CurrentAccess
) -> list[ItemTagOut]:
    """Tag an item with its owner's, the person's or one of their groups' tag
    (see ``Access.may_tag``); the tag is created if that owner has none of
    that name (any case), which for a group needs member rights there."""
    item = _item(db, access, item_id)
    library_id = body.library_id
    if library_id is None:
        writable = access.can_write(item.library_id)
        library_id = item.library_id if writable else access.own_library
    if not access.can_read(library_id):
        raise HTTPException(404, "library not found")
    if not access.may_tag(library_id, item):
        raise Forbidden("you may not change this item's tags")
    try:
        known = organize.find_tag(db, library_id, body.name)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if known is None:
        access.require_write(library_id)  # new tags of a group: members
    try:
        organize.tag_item(
            db, item, body.name, library_id=library_id, user_id=access.user.id
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    db.commit()
    return item_tags(item, access)


@router.delete("/api/items/{item_id}/tags/{tag_id}")
def remove_tag(
    item_id: uuid.UUID, tag_id: uuid.UUID, db: DB, access: CurrentAccess
) -> list[ItemTagOut]:
    item = _item(db, access, item_id)
    tag = _tag(db, access, tag_id)
    if not access.may_tag(tag.library_id, item):
        raise Forbidden("you may not change this item's tags")
    organize.untag_item(item, tag_id)
    db.commit()
    return item_tags(item, access)


@router.patch("/api/tags/{tag_id}")
def change_tag(
    tag_id: uuid.UUID, body: TagChange, db: DB, access: CurrentAccess
) -> TagOut:
    """Rename a tag everywhere (409 if another tag of its owner has that
    name), set its colour or description, or give it to another owner."""
    tag = _tag(db, access, tag_id, write=True)
    target = body.library_id
    if target is not None and target != tag.library_id:
        access.target_library(target)
        if organize.find_tag(db, target, body.name or tag.name) is not None:
            raise HTTPException(409, "the new owner has a tag of that name already")
        tag.library_id = target
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
    return next(t for t in list_tags(db, access) if t.id == tag.id)


@router.delete("/api/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: uuid.UUID, db: DB, access: CurrentAccess) -> Response:
    """Remove a tag from every item and delete it."""
    tag = _tag(db, access, tag_id, write=True)
    for item in db.scalars(select(Item).join(ItemTag).where(ItemTag.tag_id == tag_id)):
        organize.untag_item(item, tag_id)
    db.delete(tag)
    db.commit()
    return Response(status_code=204)


# Collections


def _collection_out(db: DB, access: Access, collection: Collection) -> CollectionOut:
    if collection.rules is not None:
        count, recent = _smart_contents(db, access, collection)
        direct = count
    else:
        count, recent = _contents(db, access, collection.id).get(collection.id, (0, []))
        direct = _direct_counts(db, access, collection.id).get(collection.id, 0)
    return CollectionOut(
        id=collection.id,
        library_id=collection.library_id,
        name=collection.name,
        description=collection.description,
        parent_id=collection.parent_id,
        count=count,
        direct=direct,
        recent=recent,
        pinned=collection.id in _pinned(db, access),
        rules=_rules(collection),
    )


def _rules(collection: Collection) -> organize.Rules | None:
    if collection.rules is None:
        return None
    return organize.Rules.model_validate(collection.rules)


def _smart_contents(
    db: DB, access: Access, collection: Collection, per_collection: int = 3
) -> tuple[int, list[ItemPreview]]:
    """How many papers match a smart collection's rules (of those the
    person can read), and the last added."""
    conditions = [
        *organize.matching(db, collection),
        Item.deleted_at.is_(None),
        access.item_filter(),
    ]
    count = db.scalar(select(func.count()).select_from(Item).where(*conditions))
    recent = db.execute(
        select(Item.id, Item.title)
        .where(*conditions)
        .order_by(Item.id.desc())
        .limit(per_collection)
    )
    return count or 0, [ItemPreview(id=i, title=title) for i, title in recent]


def _pinned(db: DB, access: Access) -> set[uuid.UUID]:
    return set(
        db.scalars(
            select(PinnedCollection.collection_id).where(
                PinnedCollection.user_id == access.user.id
            )
        )
    )


def _direct_counts(
    db: DB, access: Access, only: uuid.UUID | None = None
) -> dict[uuid.UUID, int]:
    query = (
        select(CollectionItem.collection_id, func.count())
        .join(Item, Item.id == CollectionItem.item_id)
        .where(Item.deleted_at.is_(None), access.item_filter())
        .group_by(CollectionItem.collection_id)
    )
    if only is not None:
        query = query.where(CollectionItem.collection_id == only)
    return {collection_id: count for collection_id, count in db.execute(query)}


@router.get("/api/collections")
def list_collections(db: DB, access: CurrentAccess) -> list[CollectionOut]:
    """The collections of the libraries the person can read, flat;
    ``parent_id`` gives the tree."""
    contents = _contents(db, access)
    direct = _direct_counts(db, access)
    pinned = _pinned(db, access)
    collections = db.scalars(
        select(Collection)
        .where(Collection.library_id.in_(access.readable))
        .order_by(func.lower(Collection.name))
    )
    result = []
    for c in collections:
        count, recent = contents.get(c.id, (0, []))
        if c.rules is not None:
            count, recent = _smart_contents(db, access, c)
        result.append(
            CollectionOut(
                id=c.id,
                library_id=c.library_id,
                name=c.name,
                description=c.description,
                parent_id=c.parent_id,
                count=count,
                direct=count if c.rules is not None else direct.get(c.id, 0),
                recent=recent,
                pinned=c.id in pinned,
                rules=_rules(c),
            )
        )
    return result


def _contents(
    db: DB, access: Access, root: uuid.UUID | None = None, per_collection: int = 3
) -> dict[uuid.UUID, tuple[int, list[ItemPreview]]]:
    """Per collection, its items (that the person can read) including those
    of the collections inside: how many, and the last added (newest first).
    Only ``root`` if given."""
    start = select(Collection.id.label("root"), Collection.id.label("member")).where(
        Collection.library_id.in_(access.readable)
    )
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
        .where(Item.deleted_at.is_(None), access.item_filter())
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
def create_collection(
    body: CollectionIn, db: DB, access: CurrentAccess
) -> CollectionOut:
    try:
        name = organize.clean_name(body.name)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if body.parent_id is not None:
        parent = _collection(db, access, body.parent_id, write=True)
        if body.library_id not in (None, parent.library_id):
            raise HTTPException(409, "collections nest only within one library")
        if parent.rules is not None:
            raise HTTPException(409, "a smart collection holds no other collections")
        library_id = parent.library_id
    else:
        library_id = access.target_library(body.library_id)
    collection = Collection(
        library_id=library_id,
        name=name,
        description=body.description,
        parent_id=body.parent_id,
        created_by=access.user.id,
        change=0,
        rules=body.rules.model_dump(mode="json") if body.rules else None,
    )
    db.add(collection)
    db.commit()
    return _collection_out(db, access, collection)


@router.patch("/api/collections/{collection_id}")
def change_collection(
    collection_id: uuid.UUID, body: CollectionChange, db: DB, access: CurrentAccess
) -> CollectionChanged:
    """Rename, describe or move a collection (not into itself), also into
    another library the person may change."""
    collection = _collection(db, access, collection_id, write=True)
    given = body.model_fields_set
    left_out = 0
    try:
        if "name" in given and body.name is not None:
            collection.name = organize.clean_name(body.name)
        if "description" in given:
            collection.description = body.description
        target = body.library_id
        if target is not None and target != collection.library_id:
            access.target_library(target)  # readable and writable
            if body.add_papers:
                # Papers the person may change become the target's; others
                # stay where they are (and leave the collection).
                for item in _papers_in(db, access, collection):
                    if access.can_write_item(item) and not access.may_hold(
                        target, item
                    ):
                        library.set_owner(db, item, target)
                db.flush()
            left_out = organize.move_to_library(
                db,
                collection,
                target,
                may_hold=lambda item: access.may_hold(target, item),
            )
            db.flush()
        if "parent_id" in given:
            organize.move_collection(db, collection, body.parent_id)
        if "rules" in given:
            organize.make_smart(db, collection, body.rules)
    except organize.NotFound as error:
        raise HTTPException(404, str(error)) from error
    except organize.Conflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    db.commit()
    return CollectionChanged(
        **_collection_out(db, access, collection).model_dump(), left_out=left_out
    )


def _papers_in(db: DB, access: Access, collection: Collection) -> list[Item]:
    """Readable items in the collection and the collections inside it."""
    ids = organize.descendants(db, collection.id)
    return list(
        db.scalars(
            select(Item)
            .join(CollectionItem)
            .where(
                CollectionItem.collection_id.in_(ids),
                access.item_filter(),
            )
        ).unique()
    )


@router.get("/api/collections/{collection_id}/move-preview")
def preview_move(
    collection_id: uuid.UUID,
    library_id: Annotated[uuid.UUID, Query(alias="library")],
    db: DB,
    access: CurrentAccess,
) -> MovePreview:
    """Before moving a collection into another library: how many of its
    papers are not in that library yet."""
    collection = _collection(db, access, collection_id, write=True)
    access.target_library(library_id)
    papers = _papers_in(db, access, collection)
    return MovePreview(
        papers=len(papers),
        not_in_library=sum(not access.may_hold(library_id, item) for item in papers),
    )


@router.delete("/api/collections/{collection_id}", status_code=204)
def delete_collection(
    collection_id: uuid.UUID, db: DB, access: CurrentAccess
) -> Response:
    """Delete a collection and its subcollections; items stay in the library."""
    collection = _collection(db, access, collection_id, write=True)
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


@router.put("/api/collections/{collection_id}/pin", status_code=204)
def pin_collection(collection_id: uuid.UUID, db: DB, access: CurrentAccess) -> Response:
    """Pin the collection to the person's sidebar (readers may too)."""
    _collection(db, access, collection_id)
    db.execute(
        insert(PinnedCollection)
        .values(user_id=access.user.id, collection_id=collection_id)
        .on_conflict_do_nothing()
    )
    db.commit()
    return Response(status_code=204)


@router.delete("/api/collections/{collection_id}/pin", status_code=204)
def unpin_collection(
    collection_id: uuid.UUID, db: DB, access: CurrentAccess
) -> Response:
    _collection(db, access, collection_id)
    db.execute(
        delete(PinnedCollection).where(
            PinnedCollection.user_id == access.user.id,
            PinnedCollection.collection_id == collection_id,
        )
    )
    db.commit()
    return Response(status_code=204)


@router.post("/api/collections/{collection_id}/items")
def add_items(
    collection_id: uuid.UUID, body: ItemIds, db: DB, access: CurrentAccess
) -> CollectionOut:
    """Add items; those the collection may not hold (a group's collection
    holds only that group's items) or the person cannot read are skipped."""
    collection = _collection(db, access, collection_id, write=True)
    _not_smart(collection)
    organize.add_to_collection(
        db,
        collection,
        body.item_ids,
        access.user.id,
        may_hold=lambda item: access.may_hold(collection.library_id, item),
    )
    db.commit()
    return _collection_out(db, access, collection)


@router.delete("/api/collections/{collection_id}/items/{item_id}")
def remove_item(
    collection_id: uuid.UUID, item_id: uuid.UUID, db: DB, access: CurrentAccess
) -> CollectionOut:
    collection = _collection(db, access, collection_id, write=True)
    _not_smart(collection)
    item = _item(db, access, item_id)
    item.collection_links = [
        link for link in item.collection_links if link.collection_id != collection_id
    ]
    db.commit()
    return _collection_out(db, access, collection)
