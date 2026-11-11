"""Syncing (docs/apps.md, "Offline and sync"): everything the person sees
that changed since a change number, in one call, and what is gone."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import exists, or_, select

from paperus import changes
from paperus.api.annotations import AnnotationOut, annotation_out
from paperus.api.deps import DB, CurrentAccess
from paperus.api.items import ItemOut, Reading, item_out
from paperus.api.notes import NoteDetail, note_out
from paperus.api.organize import CollectionOut, TagOut, collection_out, tag_outs
from paperus.models import (
    Annotation,
    AnnotationShare,
    Collection,
    File,
    Item,
    ItemView,
    Note,
    Removal,
    Tag,
    Version,
)

router = APIRouter(tags=["sync"])


class View(BaseModel):
    """When the person last opened a paper, and where they stopped."""

    item_id: uuid.UUID
    viewed_at: datetime
    reading: Reading | None


class Removed(BaseModel):
    id: uuid.UUID
    kind: str
    """``item``, ``note``, ``tag``, ``collection``, ``file`` or ``annotation``."""


class Changes(BaseModel):
    change: int
    """The number to pass as ``since`` next time."""
    libraries: list[uuid.UUID]
    """The libraries the person reads now: what a device keeps from others
    is out of their reach (a group left); one new here is synced from 0."""
    removed: list[Removed]
    """Gone (deleted for good, or moved out of a library listed): applied
    before the rest, which is as things are now."""
    items: list[ItemOut]
    """Changed, trashed ones too (``deleted_at``)."""
    notes: list[NoteDetail]
    tags: list[TagOut]
    collections: list[CollectionOut]
    annotations: list[AnnotationOut]
    """The person's own and those shared with them."""
    views: list[View]


@router.get("/api/changes")
def changes_since(
    db: DB,
    access: CurrentAccess,
    since: Annotated[int, Query(ge=0)] = 0,
    library: Annotated[list[uuid.UUID] | None, Query()] = None,
) -> Changes:
    """Everything the person sees that changed after change number
    ``since`` (all of it with 0), in change order, and what is gone since;
    ``library`` (repeatable) for only these libraries, e.g. one the person
    may read since. Number first: what changes meanwhile comes next time."""
    number = changes.current_change(db)
    libraries = access.readable
    if library is not None:
        libraries = [i for i in library if access.can_read(i)]
    items = db.scalars(
        select(Item)
        .where(Item.library_id.in_(libraries), Item.change > since)
        .order_by(Item.change, Item.id)
    )
    notes = db.scalars(
        select(Note)
        .where(Note.library_id.in_(libraries), Note.change > since)
        .order_by(Note.change, Note.id)
    )
    collections = db.scalars(
        select(Collection)
        .where(Collection.library_id.in_(libraries), Collection.change > since)
        .order_by(Collection.change, Collection.id)
    )
    shared = exists().where(
        AnnotationShare.user_id == Annotation.user_id,
        AnnotationShare.item_id == Item.id,
    )
    annotations = db.scalars(
        select(Annotation)
        .join(File, File.id == Annotation.file_id)
        .join(Version, Version.id == File.version_id)
        .join(Item, Item.id == Version.item_id)
        .where(
            Item.library_id.in_(libraries),
            Annotation.change > since,
            or_(Annotation.user_id == access.user.id, shared),
        )
        .order_by(Annotation.change, Annotation.id)
    )
    views = db.scalars(
        select(ItemView)
        .join(Item, Item.id == ItemView.item_id)
        .where(
            ItemView.user_id == access.user.id,
            Item.library_id.in_(libraries),
            ItemView.change > since,
        )
        .order_by(ItemView.change)
    )
    # From 0 a device has nothing to remove.
    removed = (
        db.scalars(
            select(Removal)
            .where(Removal.library_id.in_(libraries), Removal.change > since)
            .order_by(Removal.change)
        )
        if since
        else []
    )
    names: dict[uuid.UUID, str] = {}
    return Changes(
        change=number,
        libraries=libraries,
        removed=[Removed(id=r.record_id, kind=r.kind) for r in removed],
        items=[item_out(item, access) for item in items],
        notes=[
            NoteDetail(**note_out(db, note, access).model_dump(), text=note.text)
            for note in notes
        ],
        tags=tag_outs(db, access, Tag.library_id.in_(libraries) & (Tag.change > since)),
        collections=[collection_out(db, access, c) for c in collections],
        annotations=[annotation_out(db, access, a, names) for a in annotations],
        views=[
            View(
                item_id=view.item_id,
                viewed_at=view.viewed_at,
                reading=Reading.model_validate(view.reading) if view.reading else None,
            )
            for view in views
        ],
    )
