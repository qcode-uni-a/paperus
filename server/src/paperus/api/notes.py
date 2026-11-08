"""Notes: Markdown with an owner, about papers (or none), in collections."""

import re
import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from paperus import library, notes, organize
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.api.items import Owner, require_readable
from paperus.api.organize import _collection
from paperus.jobs import queue_note_embedding
from paperus.models import (
    Collection,
    CollectionNote,
    Item,
    Note,
    NoteItem,
    NoteRevision,
    User,
)

router = APIRouter(tags=["notes"])

EXCERPT = 200


class NoteLinkOut(BaseModel):
    item_id: uuid.UUID
    title: str
    page: int | None


class NoteOut(BaseModel):
    id: uuid.UUID
    library_id: uuid.UUID
    """The owner: a person's or a group's library."""
    title: str
    excerpt: str
    """The start of the text after the title, as plain as it comes."""
    items: list[NoteLinkOut]
    """Papers the note is about that the reader can see."""
    collection_ids: list[uuid.UUID]
    """Collections the reader can see that hold the note."""
    created_at: datetime
    changed_at: datetime
    changed_by: str | None
    change: int
    deleted_at: datetime | None


class NoteDetail(NoteOut):
    text: str


class LinkIn(BaseModel):
    item_id: uuid.UUID
    page: int | None = Field(default=None, ge=1)


class NoteIn(BaseModel):
    text: str = Field(default="", max_length=1_000_000)
    library_id: uuid.UUID | None = None
    """The owner; by default the person's default owner."""
    items: list[LinkIn] = []
    collection_id: uuid.UUID | None = None
    """Put it into this collection right away."""


class NoteChange(BaseModel):
    text: str = Field(max_length=1_000_000)


class LinkChange(BaseModel):
    page: int | None = Field(default=None, ge=1)


class NoteIds(BaseModel):
    note_ids: list[uuid.UUID]


class RevisionOut(BaseModel):
    id: uuid.UUID
    text: str
    written_by: str | None
    written_at: datetime


def _username(db: DB, user_id: uuid.UUID | None) -> str | None:
    """How the person is shown: their display name, else username."""
    user = db.get(User, user_id) if user_id else None
    return (user.display_name or user.username) if user else None


def _excerpt(note: Note) -> str:
    lines = note.text.strip().splitlines()
    rest = " ".join(line.strip() for line in lines[1:] if line.strip())
    rest = re.sub(r"[#*_`>]+", "", rest)
    return rest[:EXCERPT] + ("…" if len(rest) > EXCERPT else "")


def note_out(db: DB, note: Note, access: Access) -> NoteOut:
    return NoteOut(
        id=note.id,
        library_id=note.library_id,
        title=note.title,
        excerpt=_excerpt(note),
        items=[
            NoteLinkOut(item_id=link.item_id, title=link.item.title, page=link.page)
            for link in note.item_links
            if access.can_read_item(link.item) and link.item.deleted_at is None
        ],
        collection_ids=[
            link.collection_id
            for link in note.collection_links
            if access.can_read(link.collection.library_id)
        ],
        created_at=note.created_at,
        changed_at=note.changed_at,
        changed_by=_username(db, note.changed_by),
        change=note.change,
        deleted_at=note.deleted_at,
    )


def note_detail(db: DB, note: Note, access: Access, response: Response) -> NoteDetail:
    response.headers["ETag"] = f'"{notes.etag(note)}"'
    return NoteDetail(**note_out(db, note, access).model_dump(), text=note.text)


def get_note(
    db: DB, access: Access, note_id: uuid.UUID, *, write: bool = False
) -> Note:
    note = db.get(Note, note_id)
    if note is None or not access.can_read(note.library_id):
        raise HTTPException(404, "note not found")
    if write:
        access.require_write(note.library_id)
    return note


def _readable_item(db: DB, access: Access, item_id: uuid.UUID) -> Item:
    item = db.get(Item, item_id)
    if item is None or not access.can_read_item(item) or item.deleted_at:
        raise HTTPException(404, "item not found")
    return item


def _parse_if_match(value: str | None) -> str:
    if value is None:
        raise HTTPException(428, "If-Match header with the note's ETag required")
    return value.removeprefix("W/").strip().strip('"')


@router.get("/api/notes")
def list_notes(
    response: Response,
    db: DB,
    access: CurrentAccess,
    item: uuid.UUID | None = None,
    collection: uuid.UUID | None = None,
    nested: bool = True,
    trashed: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NoteOut]:
    """Notes the person can read, last changed first: all of them, those
    about a paper (``item``) or in a collection (with its subcollections
    unless ``nested=false``); ``trashed=true`` lists the trash instead.
    ``X-Total-Count`` is the number of matching notes."""
    require_readable(db, access, Collection, [collection] if collection else [])
    conditions = [
        Note.library_id.in_(access.readable),
        Note.deleted_at.is_not(None) if trashed else Note.deleted_at.is_(None),
    ]
    if item is not None:
        conditions.append(
            Note.id.in_(select(NoteItem.note_id).where(NoteItem.item_id == item))
        )
    if collection is not None:
        ids = organize.descendants(db, collection) if nested else [collection]
        conditions.append(
            Note.id.in_(
                select(CollectionNote.note_id).where(
                    CollectionNote.collection_id.in_(ids)
                )
            )
        )
    total = db.scalar(select(func.count()).select_from(Note).where(*conditions))
    response.headers["X-Total-Count"] = str(total or 0)
    found = db.scalars(
        select(Note)
        .where(*conditions)
        .order_by(Note.changed_at.desc(), Note.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [note_out(db, note, access) for note in found]


@router.post("/api/notes", status_code=201)
def create_note(
    body: NoteIn, request: Request, response: Response, db: DB, access: CurrentAccess
) -> NoteDetail:
    """A new note for the given owner (or the person's default owner), about
    the given papers, optionally put into a collection."""
    owner = access.target_library(body.library_id)
    links = [
        (_readable_item(db, access, link.item_id), link.page) for link in body.items
    ]
    collection = (
        _collection(db, access, body.collection_id, write=True)
        if body.collection_id
        else None
    )
    note = notes.create(db, owner, body.text, access.user.id)
    seen: set[uuid.UUID] = set()
    for item, page in links:
        if item.id not in seen:
            seen.add(item.id)
            note.item_links.append(
                NoteItem(item_id=item.id, page=page, added_by=access.user.id)
            )
    if collection is not None:
        if not access.may_hold(collection.library_id, note):
            raise HTTPException(
                409, "a group's collection holds only notes the group owns"
            )
        note.collection_links.append(
            CollectionNote(collection_id=collection.id, added_by=access.user.id)
        )
    db.commit()
    queue_note_embedding(request.app.state.jobs, note.id)
    return note_detail(db, note, access, response)


@router.get("/api/notes/{note_id}")
def read_note(
    note_id: uuid.UUID, response: Response, db: DB, access: CurrentAccess
) -> NoteDetail:
    """The note with its text; the ``ETag`` goes into ``If-Match`` when saving."""
    return note_detail(db, get_note(db, access, note_id), access, response)


@router.patch("/api/notes/{note_id}")
def change_note(
    note_id: uuid.UUID,
    body: NoteChange,
    request: Request,
    response: Response,
    db: DB,
    access: CurrentAccess,
    if_match: Annotated[str | None, Header()] = None,
) -> NoteDetail:
    """Save the text. Needs ``If-Match`` with the ETag the editor started
    from: 412 if someone else saved in between (then reload and merge)."""
    note = get_note(db, access, note_id, write=True)
    if note.deleted_at is not None:
        raise HTTPException(409, "the note is in the trash")
    try:
        note = notes.save(
            db, note.id, body.text, _parse_if_match(if_match), access.user.id
        )
    except notes.Conflict as error:
        raise HTTPException(412, "the note changed in the meantime") from error
    db.commit()
    queue_note_embedding(request.app.state.jobs, note.id)
    return note_detail(db, note, access, response)


@router.put("/api/notes/{note_id}/items/{item_id}")
def link_item(
    note_id: uuid.UUID,
    item_id: uuid.UUID,
    body: LinkChange,
    response: Response,
    db: DB,
    access: CurrentAccess,
) -> NoteDetail:
    """Say the note is about the paper (at a page); changes the page if it
    is linked already."""
    note = get_note(db, access, note_id, write=True)
    item = _readable_item(db, access, item_id)
    for link in note.item_links:
        if link.item_id == item.id:
            link.page = body.page
            break
    else:
        note.item_links.append(
            NoteItem(item_id=item.id, page=body.page, added_by=access.user.id)
        )
    db.commit()
    return note_detail(db, note, access, response)


@router.delete("/api/notes/{note_id}/items/{item_id}")
def unlink_item(
    note_id: uuid.UUID,
    item_id: uuid.UUID,
    response: Response,
    db: DB,
    access: CurrentAccess,
) -> NoteDetail:
    # Also links to papers the person cannot see (any more) or that are in
    # the trash: the note's writers may tidy them up.
    note = get_note(db, access, note_id, write=True)
    note.item_links = [link for link in note.item_links if link.item_id != item_id]
    db.commit()
    return note_detail(db, note, access, response)


@router.put("/api/notes/{note_id}/owner")
def set_note_owner(
    note_id: uuid.UUID, body: Owner, response: Response, db: DB, access: CurrentAccess
) -> NoteDetail:
    """Give the note to another owner the person may add to. Collections of a
    group that no longer owns it let it go."""
    note = get_note(db, access, note_id, write=True)
    access.target_library(body.library_id)
    note.library_id = body.library_id
    note.collection_links = [
        link
        for link in note.collection_links
        if access.may_hold(link.collection.library_id, note)
    ]
    db.commit()
    return note_detail(db, note, access, response)


@router.delete("/api/notes/{note_id}", status_code=204)
def trash_note(note_id: uuid.UUID, db: DB, access: CurrentAccess) -> Response:
    note = get_note(db, access, note_id, write=True)
    library.trash(note, access.user.id)
    db.commit()
    return Response(status_code=204)


@router.post("/api/notes/{note_id}/restore")
def restore_note(
    note_id: uuid.UUID, response: Response, db: DB, access: CurrentAccess
) -> NoteDetail:
    note = get_note(db, access, note_id, write=True)
    library.restore(note)
    db.commit()
    return note_detail(db, note, access, response)


@router.get("/api/notes/{note_id}/history")
def note_history(
    note_id: uuid.UUID, db: DB, access: CurrentAccess
) -> list[RevisionOut]:
    """Earlier texts of the note, newest first."""
    note = get_note(db, access, note_id)
    revisions = db.scalars(
        select(NoteRevision)
        .where(NoteRevision.note_id == note.id)
        .order_by(NoteRevision.id.desc())
    )
    return [
        RevisionOut(
            id=r.id,
            text=r.text,
            written_by=_username(db, r.written_by),
            written_at=r.written_at,
        )
        for r in revisions
    ]


@router.get("/api/notes/{note_id}/markdown")
def note_markdown(note_id: uuid.UUID, db: DB, access: CurrentAccess) -> Response:
    """The note as a Markdown file."""
    note = get_note(db, access, note_id)
    name = re.sub(r"[^\w.-]+", "-", note.title).strip("-")[:80] or "note"
    return Response(
        note.text,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(name)}.md"
        },
    )


@router.post("/api/collections/{collection_id}/notes", status_code=204)
def add_notes(
    collection_id: uuid.UUID, body: NoteIds, db: DB, access: CurrentAccess
) -> Response:
    """Put notes into a collection; those it may not hold (a group's
    collection holds only the group's notes) or unknown ones are skipped."""
    collection = _collection(db, access, collection_id, write=True)
    for note_id in dict.fromkeys(body.note_ids):
        note = db.get(Note, note_id)
        if (
            note is None
            or not access.can_read(note.library_id)
            or not access.may_hold(collection.library_id, note)
            or any(
                link.collection_id == collection.id for link in note.collection_links
            )
        ):
            continue
        note.collection_links.append(
            CollectionNote(collection_id=collection.id, added_by=access.user.id)
        )
    db.commit()
    return Response(status_code=204)


@router.delete("/api/collections/{collection_id}/notes/{note_id}", status_code=204)
def remove_note(
    collection_id: uuid.UUID, note_id: uuid.UUID, db: DB, access: CurrentAccess
) -> Response:
    _collection(db, access, collection_id, write=True)
    note = get_note(db, access, note_id)
    note.collection_links = [
        link for link in note.collection_links if link.collection_id != collection_id
    ]
    db.commit()
    return Response(status_code=204)
