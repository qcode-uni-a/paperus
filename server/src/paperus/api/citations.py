"""Citation export: BibTeX or CSL-JSON for papers, a collection or everything."""

import json
import re
import uuid
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select

from paperus import citations, organize
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.api.organize import item_tags
from paperus.models import Collection, Item

router = APIRouter(tags=["citations"])

Format = Literal["bibtex", "csl-json"]


def export_items(
    db: DB,
    access: Access,
    *,
    item_ids: list[uuid.UUID] | None = None,
    collection_id: uuid.UUID | None = None,
    nested: bool = True,
) -> tuple[list[Item], str]:
    """The readable, untrashed items to export (oldest first, so suffixes of
    equal keys stay put) and a name for the file."""
    query = select(Item).where(
        access.item_filter(access.readable), Item.deleted_at.is_(None)
    )
    name = "paperus"
    if item_ids is not None:
        query = query.where(Item.id.in_(item_ids))
    if collection_id is not None:
        collection = db.get(Collection, collection_id)
        if collection is None or not access.can_read(collection.library_id):
            raise HTTPException(404, "No such collection")
        query = query.where(
            Item.id.in_(organize.item_ids_in(db, collection_id, nested=nested))
        )
        name = collection.name
    items = list(db.scalars(query.order_by(Item.id)))
    if item_ids is not None and len(item_ids) == 1 and items:
        name = citations.keyed(items)[0][0]
    return items, name


def render(items: list[Item], format: Format, access: Access) -> str:
    if format == "bibtex":
        return citations.bibtex(
            items, lambda item: [tag.name for tag in item_tags(item, access)]
        )
    return json.dumps(citations.csl_json(items), ensure_ascii=False, indent=2) + "\n"


@router.get("/api/citations")
def export_citations(
    db: DB,
    access: CurrentAccess,
    format: Format = "bibtex",
    item: Annotated[list[uuid.UUID] | None, Query()] = None,
    collection: uuid.UUID | None = None,
    nested: bool = True,
    download: bool = False,
) -> Response:
    """Citations for the given papers (``item``, repeatable), a collection
    (with its subcollections unless ``nested=false``) or, with neither,
    everything the person can read. ``download=true`` offers it as a file
    (``.bib`` or ``.json``)."""
    items, name = export_items(
        db, access, item_ids=item, collection_id=collection, nested=nested
    )
    media = (
        "application/x-bibtex"
        if format == "bibtex"
        else "application/vnd.citationstyles.csl+json"
    )
    filename = re.sub(r"[^\w.-]+", "-", name).strip("-") or "paperus"
    filename += ".bib" if format == "bibtex" else ".json"
    disposition = "attachment" if download else "inline"
    return Response(
        render(items, format, access),
        media_type=f"{media}; charset=utf-8",
        headers={
            "Content-Disposition": f"{disposition}; filename*=utf-8''{quote(filename)}"
        },
    )
