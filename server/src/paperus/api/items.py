"""Items: adding by DOI, listing and reading."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from paperus import metadata
from paperus.api.deps import DB, CurrentUser
from paperus.models import Item

router = APIRouter(prefix="/api/items", tags=["items"])


class AddItemRequest(BaseModel):
    doi: str


class ItemOut(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    doi: str | None
    authors: list[str]
    year: int | None
    container_title: str | None
    created_at: datetime


class ItemDetail(ItemOut):
    csl: dict[str, Any]


def _authors(csl: dict[str, Any]) -> list[str]:
    names = []
    for author in csl.get("author", []):
        if "family" in author:
            names.append(
                ", ".join(filter(None, [author["family"], author.get("given")]))
            )
        elif "literal" in author:
            names.append(author["literal"])
    return names


def _year(csl: dict[str, Any]) -> int | None:
    for key in ("issued", "published-print", "published-online"):
        try:
            return int(csl[key]["date-parts"][0][0])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return None


def _container_title(csl: dict[str, Any]) -> str | None:
    value = csl.get("container-title")
    if isinstance(value, list):
        value = value[0] if value else None
    return value or None


def item_out(item: Item) -> ItemOut:
    return ItemOut(
        id=item.id,
        type=item.type,
        title=item.title,
        doi=item.doi,
        authors=_authors(item.csl),
        year=_year(item.csl),
        container_title=_container_title(item.csl),
        created_at=item.created_at,
    )


def item_detail(item: Item) -> ItemDetail:
    return ItemDetail(**item_out(item).model_dump(), csl=item.csl)


@router.post("", status_code=201)
def add_item(
    body: AddItemRequest,
    request: Request,
    response: Response,
    db: DB,
    user: CurrentUser,
) -> ItemDetail:
    """Add an item by DOI; returns the existing item if the DOI is already there."""
    try:
        doi = metadata.normalize_doi(body.doi)
    except metadata.InvalidDOI as error:
        raise HTTPException(422, "not a valid DOI") from error

    existing = db.scalar(select(Item).where(Item.doi == doi))
    if existing is not None:
        response.status_code = 200
        return item_detail(existing)

    try:
        csl = metadata.fetch_csl(request.app.state.http, doi)
    except metadata.DOINotFound as error:
        raise HTTPException(404, "DOI not found") from error
    except metadata.MetadataUnavailable as error:
        raise HTTPException(502, "metadata lookup failed") from error

    csl = {**csl, "type": metadata.csl_type(csl)}
    item = Item(
        type=csl["type"],
        title=metadata.csl_title(csl),
        doi=doi,
        csl=csl,
        added_by=user.id,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        # Someone added the same DOI meanwhile.
        db.rollback()
        response.status_code = 200
        return item_detail(db.scalars(select(Item).where(Item.doi == doi)).one())
    db.refresh(item)
    return item_detail(item)


@router.get("")
def list_items(
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: uuid.UUID | None = None,
) -> list[ItemOut]:
    """Newest first; pass the last ``id`` as ``before`` for the next page."""
    query = select(Item).order_by(Item.id.desc()).limit(limit)
    if before is not None:
        query = query.where(Item.id < before)
    return [item_out(item) for item in db.scalars(query)]


@router.get("/{item_id}")
def get_item(item_id: uuid.UUID, db: DB, user: CurrentUser) -> ItemDetail:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    return item_detail(item)
