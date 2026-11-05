"""Items and their versions: adding by identifier or by hand, reading."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Self

import httpx2
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from paperus import changes, library, metadata
from paperus.api.deps import DB, CurrentUser
from paperus.api.files import FileOut, file_out
from paperus.identifiers import InvalidIdentifier, Scheme, implied_by_doi, normalize
from paperus.models import Item, MetadataSource, TextStatus, Version, VersionKind

router = APIRouter(tags=["items"])


class IdentifierIn(BaseModel):
    scheme: Scheme
    value: str


class VersionIn(BaseModel):
    """A version by DOI (metadata is looked up) or with metadata typed in.

    Examples: ``{"doi": "10.1038/…"}``; meeting notes:
    ``{"metadata": {"type": "document", "genre": "Meeting notes",
    "title": "Group meeting", "issued": {"date-parts": [[2026, 11, 4]]}}}``.
    """

    doi: str | None = None
    metadata: dict[str, Any] | None = None
    identifiers: list[IdentifierIn] = Field(default_factory=list)
    kind: VersionKind | None = None
    label: str | None = None

    @model_validator(mode="after")
    def doi_or_metadata(self) -> Self:
        if (self.doi is None) == (self.metadata is None):
            raise ValueError("give either doi or metadata")
        if self.metadata is not None and not self.metadata.get("title"):
            raise ValueError("metadata needs a title")
        return self


class IdentifierOut(BaseModel):
    scheme: Scheme
    value: str


class VersionOut(BaseModel):
    id: uuid.UUID
    kind: VersionKind
    label: str | None
    pinned: bool
    metadata_source: MetadataSource
    identifiers: list[IdentifierOut]
    csl: dict[str, Any]
    files: list[FileOut]
    created_at: datetime


class ItemOut(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    authors: list[str]
    year: int | None
    container_title: str | None
    identifiers: list[IdentifierOut]
    created_at: datetime
    change: int
    deleted_at: datetime | None
    processing: bool
    """Files are still being read (text, and metadata for uploads)."""


class ItemDetail(ItemOut):
    csl: dict[str, Any]
    """Metadata for citing: the preferred version's plus manual edits."""
    overrides: dict[str, Any]
    preferred_version_id: uuid.UUID | None
    versions: list[VersionOut]


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


def _identifiers(version: Version) -> list[IdentifierOut]:
    return [
        IdentifierOut(scheme=Scheme(i.scheme), value=i.value)
        for i in version.identifiers
    ]


def item_out(item: Item) -> ItemOut:
    csl = library.citation_csl(item)
    return ItemOut(
        id=item.id,
        type=item.type,
        title=item.title,
        authors=_authors(csl),
        year=_year(csl),
        container_title=_container_title(csl),
        identifiers=[i for v in item.versions for i in _identifiers(v)],
        created_at=item.created_at,
        change=item.change,
        deleted_at=item.deleted_at,
        processing=any(
            f.text_status == TextStatus.PENDING and f.deleted_at is None
            for v in item.versions
            for f in v.files
        ),
    )


def version_out(version: Version) -> VersionOut:
    return VersionOut(
        id=version.id,
        kind=VersionKind(version.kind),
        label=version.label,
        pinned=version.pinned,
        metadata_source=MetadataSource(version.metadata_source),
        identifiers=_identifiers(version),
        csl=version.csl,
        files=[file_out(f) for f in version.files],
        created_at=version.created_at,
    )


def item_detail(item: Item, response: Response | None = None) -> ItemDetail:
    """The item; also sets its ``ETag`` (the change number) on ``response``."""
    if response is not None:
        response.headers["ETag"] = f'"{item.change}"'
    preferred = library.preferred_version(item)
    return ItemDetail(
        **item_out(item).model_dump(),
        csl=library.citation_csl(item),
        overrides=item.overrides,
        preferred_version_id=preferred.id if preferred else None,
        versions=[version_out(v) for v in item.versions],
    )


class ResolvedVersion(BaseModel):
    kind: VersionKind
    label: str | None
    csl: dict[str, Any]
    source: MetadataSource
    identifiers: list[tuple[Scheme, str]]


def _normalized_identifiers(body: VersionIn) -> list[tuple[Scheme, str]]:
    try:
        identifiers = [
            (i.scheme, normalize(i.scheme, i.value)) for i in body.identifiers
        ]
        if body.doi is not None:
            doi = normalize(Scheme.DOI, body.doi)
            identifiers = [(Scheme.DOI, doi), *implied_by_doi(doi), *identifiers]
    except InvalidIdentifier as error:
        raise HTTPException(422, str(error)) from error
    return identifiers


def _resolve(
    body: VersionIn, identifiers: list[tuple[Scheme, str]], http: httpx2.Client
) -> ResolvedVersion:
    """Metadata for the version: looked up for a DOI, otherwise as given."""
    if body.metadata is not None:
        return ResolvedVersion(
            kind=body.kind or VersionKind.OTHER,
            label=body.label,
            csl=body.metadata,
            source=MetadataSource.MANUAL,
            identifiers=identifiers,
        )
    doi = identifiers[0][1]
    try:
        csl, kind = metadata.lookup_doi(http, doi, body.kind)
    except metadata.DOINotFound as error:
        raise HTTPException(404, "DOI not found") from error
    except metadata.MetadataUnavailable as error:
        raise HTTPException(502, "metadata lookup failed") from error
    return ResolvedVersion(
        kind=kind,
        label=body.label,
        csl=csl,
        source=MetadataSource.LOOKUP,
        identifiers=identifiers,
    )


def _identifier_conflict(error: library.IdentifierTaken) -> HTTPException:
    return HTTPException(
        409,
        {
            "message": "identifier belongs to another item",
            "item_id": str(error.item_id),
        },
    )


@router.post("/api/items", status_code=201)
def add_item(
    body: VersionIn, request: Request, response: Response, db: DB, user: CurrentUser
) -> ItemDetail:
    """A new item; if one of its identifiers is known, the existing item."""
    identifiers = _normalized_identifiers(body)
    known = library.find_identifier(db, identifiers)
    if known is not None:
        existing = known.version.item
        if existing.deleted_at is not None:
            library.restore(existing)
            db.commit()
        response.status_code = 200
        return item_detail(existing, response)

    resolved = _resolve(body, identifiers, request.app.state.http)
    try:
        item = library.create_item(
            db,
            kind=resolved.kind,
            label=resolved.label,
            csl=resolved.csl,
            source=resolved.source,
            identifiers=resolved.identifiers,
            added_by=user.id,
        )
        db.commit()
    except IntegrityError:
        # Someone added the same identifier meanwhile.
        db.rollback()
        known = library.find_identifier(db, identifiers)
        if known is None:
            raise
        response.status_code = 200
        return item_detail(known.version.item, response)
    db.refresh(item)
    return item_detail(item, response)


def _get_item(db: DB, item_id: uuid.UUID, *, allow_trashed: bool = True) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if not allow_trashed and item.deleted_at is not None:
        raise HTTPException(409, "item is in the trash")
    return item


@router.post("/api/items/{item_id}/versions", status_code=201)
def add_version(
    item_id: uuid.UUID,
    body: VersionIn,
    request: Request,
    response: Response,
    db: DB,
    user: CurrentUser,
) -> ItemDetail:
    """Another version of an item, e.g. the published one of a preprint."""
    item = _get_item(db, item_id, allow_trashed=False)
    identifiers = _normalized_identifiers(body)
    known = library.find_identifier(db, identifiers)
    if known is not None:
        if known.version.item_id != item.id:
            raise _identifier_conflict(
                library.IdentifierTaken(
                    known.scheme, known.value, known.version.item_id
                )
            )
        response.status_code = 200
        return item_detail(item, response)

    resolved = _resolve(body, identifiers, request.app.state.http)
    try:
        library.add_version(
            db,
            item,
            kind=resolved.kind,
            label=resolved.label,
            csl=resolved.csl,
            source=resolved.source,
            identifiers=resolved.identifiers,
            created_by=user.id,
        )
        db.commit()
    except library.IdentifierTaken as error:
        raise _identifier_conflict(error) from error
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "identifier was added meanwhile") from error
    db.refresh(item)
    return item_detail(item, response)


@router.post("/api/versions/{version_id}/pin")
def pin_version(
    version_id: uuid.UUID, response: Response, db: DB, user: CurrentUser
) -> ItemDetail:
    """Cite this version, whatever its kind."""
    version = db.get(Version, version_id)
    if version is None:
        raise HTTPException(404, "version not found")
    library.pin_version(db, version.item, version)
    db.commit()
    return item_detail(version.item, response)


def _parse_if_match(value: str | None) -> int:
    """The change number from ``If-Match: "42"``; 428 without it."""
    if value is None:
        raise HTTPException(428, "If-Match header with the item's ETag required")
    try:
        return int(value.removeprefix("W/").strip().strip('"'))
    except ValueError as error:
        raise HTTPException(412, "If-Match does not match") from error


@router.put("/api/items/{item_id}/overrides")
def set_overrides(
    item_id: uuid.UUID,
    overrides: dict[str, Any],
    response: Response,
    db: DB,
    user: CurrentUser,
    if_match: Annotated[str | None, Header()] = None,
) -> ItemDetail:
    """Replace the manual edits to the metadata for citing.

    Fields set here win over every version's metadata and survive new
    lookups; ``null`` hides a field. Needs ``If-Match`` with the ETag from the
    last read, so concurrent edits are not lost (412 if the item changed).
    """
    expected = _parse_if_match(if_match)
    item = db.get(Item, item_id, with_for_update=True)
    if item is None:
        raise HTTPException(404, "item not found")
    if item.change != expected:
        raise HTTPException(412, "item changed since it was read")
    library.set_overrides(item, overrides)
    db.commit()
    return item_detail(item, response)


@router.delete("/api/items/{item_id}", status_code=204)
def trash_item(item_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    """Move to the trash; restorable with ``POST …/restore``."""
    library.trash(_get_item(db, item_id), user.id)
    db.commit()


@router.post("/api/items/{item_id}/restore")
def restore_item(
    item_id: uuid.UUID, response: Response, db: DB, user: CurrentUser
) -> ItemDetail:
    item = _get_item(db, item_id)
    library.restore(item)
    db.commit()
    return item_detail(item, response)


@router.get("/api/items")
def list_items(
    response: Response,
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: uuid.UUID | None = None,
    trashed: bool = False,
    since: Annotated[int | None, Query(ge=0)] = None,
) -> list[ItemOut]:
    """Items, newest first; ``before`` = last ``id`` for the next page.

    ``trashed=true`` lists the trash instead. ``X-Total-Count`` is the number
    of items in the list (or trash), for showing the total while paging.
    ``since=N`` is for syncing:
    every item changed after change number N, trashed or not, in change
    order; ``limit`` and ``before`` do not apply. The ``Last-Change`` header
    is the number to pass as ``since`` next time.
    """
    response.headers["Last-Change"] = str(changes.current_change(db))
    if since is not None:
        query = select(Item).where(Item.change > since).order_by(Item.change, Item.id)
        return [item_out(item) for item in db.scalars(query)]
    in_trash = Item.deleted_at.is_not(None) if trashed else Item.deleted_at.is_(None)
    total = db.scalar(select(func.count()).select_from(Item).where(in_trash)) or 0
    response.headers["X-Total-Count"] = str(total)
    query = select(Item).where(in_trash).order_by(Item.id.desc()).limit(limit)
    if before is not None:
        query = query.where(Item.id < before)
    return [item_out(item) for item in db.scalars(query)]


@router.get("/api/items/{item_id}")
def get_item(
    item_id: uuid.UUID, response: Response, db: DB, user: CurrentUser
) -> ItemDetail:
    return item_detail(_get_item(db, item_id), response)
