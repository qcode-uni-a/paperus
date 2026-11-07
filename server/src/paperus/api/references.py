"""Papers' reference lists, and the papers in the library citing a paper
(see ``paperus.item_references``)."""

import uuid
from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from paperus import item_references
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.api.imports import ImportOut, import_out
from paperus.api.items import ItemOut, get_readable_item, item_out
from paperus.jobs import queue_reference_import, queue_references
from paperus.models import Import, ImportStatus, Item, ItemReference

router = APIRouter(tags=["items"])


class ReferenceOut(BaseModel):
    position: int
    """From 1, in the order of the list."""
    text: str
    """The reference as printed."""
    title: str | None
    authors: str | None
    """Short: "Smith et al."."""
    year: int | None
    container: str | None
    """The journal or book it appeared in."""
    doi: str | None
    arxiv: str | None
    url: str | None
    item: ItemOut | None
    """The paper in the library (one the person can see) with its DOI or
    arXiv ID."""


Source = Literal["arxiv", "crossref", "pdf"]


class ReferencesOut(BaseModel):
    source: Source | None
    """Where the list came from: arXiv's LaTeX source, Crossref, or the
    paper's PDF; None while none is found."""
    checked_at: datetime | None
    """When paperus last looked for it (None: not yet)."""
    references: list[ReferenceOut]


def _reference_out(
    row: ItemReference, item: Item | None, access: Access
) -> ReferenceOut:
    return ReferenceOut(
        position=row.position,
        text=row.text,
        title=row.title,
        authors=row.authors,
        year=row.year,
        container=row.container,
        doi=row.doi,
        arxiv=row.arxiv,
        url=row.url,
        item=item_out(item, access) if item is not None else None,
    )


@router.get("/api/items/{item_id}/references")
def list_references(item_id: uuid.UUID, db: DB, access: CurrentAccess) -> ReferencesOut:
    """The paper's reference list, each reference with the paper in the
    library that has its DOI or arXiv ID (if the person can see one)."""
    item = get_readable_item(db, access, item_id)
    found = item_references.references_of(db, access, item)
    return ReferencesOut(
        source=cast(Source | None, item.references_source),
        checked_at=item.references_checked_at,
        references=[_reference_out(row, other, access) for row, other in found],
    )


@router.get("/api/items/{item_id}/cited-by")
def list_citing(item_id: uuid.UUID, db: DB, access: CurrentAccess) -> list[ItemOut]:
    """Papers the person can see whose reference lists have this paper (by
    its DOI or arXiv ID); not those in the trash or archive."""
    item = get_readable_item(db, access, item_id)
    return [
        item_out(other, access) for other in item_references.citing(db, access, item)
    ]


def _reference(db: Session, item_id: uuid.UUID, position: int) -> ItemReference:
    row = db.get(ItemReference, (item_id, position))
    if row is None:
        raise HTTPException(404, "reference not found")
    return row


@router.post("/api/items/{item_id}/references/{position}/find")
def find_reference(
    item_id: uuid.UUID, position: int, request: Request, db: DB, access: CurrentAccess
) -> ReferenceOut:
    """Look a reference without DOI or arXiv ID up on Crossref; taken only
    if the match is certain (its first author, and its title or year,
    volume and page, in the reference), else 422."""
    item = get_readable_item(db, access, item_id, allow_trashed=False)
    row = _reference(db, item.id, position)
    found = item_references.find(db, request.app.state.http, row)
    if found is None:
        raise HTTPException(422, "Crossref has no certain match for this reference")
    [(_, other)] = item_references.references_of(db, access, item, only=position)
    return _reference_out(found, other, access)


@router.post("/api/items/{item_id}/references/refresh", status_code=202)
def refresh_references(
    item_id: uuid.UUID, request: Request, db: DB, access: CurrentAccess
) -> Response:
    """Look for the paper's reference list again now, in the background
    (``checked_at`` changes when done)."""
    item = get_readable_item(db, access, item_id, allow_trashed=False)
    queue_references(request.app.state.jobs, item.id, again=True)
    return Response(status_code=202)


@router.post("/api/items/{item_id}/references/import", status_code=201)
def import_references(
    item_id: uuid.UUID,
    request: Request,
    db: DB,
    access: CurrentAccess,
    library_id: uuid.UUID | None = None,
) -> ImportOut:
    """Add the paper's references that have a DOI or arXiv ID, as an import
    (followed under ``/api/imports``) into a collection "References of …";
    those already in the library go into it too. New papers belong to
    ``library_id`` (default: the person's default owner)."""
    item = get_readable_item(db, access, item_id, allow_trashed=False)
    owner = access.target_library(library_id)
    record = Import(
        user_id=access.user.id,
        library_id=owner,
        filename=item_references.collection_name(item.title)[:255],
        format="references",
        status=ImportStatus.WAITING,
    )
    db.add(record)
    db.commit()
    queue_reference_import(request.app.state.jobs, record.id, owner, item.id)
    return import_out(record)
