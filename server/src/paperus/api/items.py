"""Items and their versions: adding by identifier or by hand, reading."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Self

import httpx2
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paperus import changes, library, merge, metadata
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.api.files import FileOut, file_out
from paperus.api.organize import ItemTagOut, item_tags
from paperus.identifiers import InvalidIdentifier, Scheme, implied_by_doi, normalize
from paperus.models import (
    Favourite,
    File,
    Item,
    ItemTag,
    ItemView,
    MetadataSource,
    TextStatus,
    Version,
    VersionKind,
)
from paperus.organize import item_ids_in

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


class ItemIn(VersionIn):
    library_id: uuid.UUID | None = None
    """The owner (a person's or a group's library); the person's default if
    not given. A paper the person can already see is not added again."""


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
    library_id: uuid.UUID
    """The owner: a person's or a group's library."""
    type: str
    title: str
    authors: list[str]
    year: int | None
    container_title: str | None
    identifiers: list[IdentifierOut]
    created_at: datetime
    change: int
    changed_at: datetime
    """When the item or its versions, files, tags or collections last changed."""
    viewed_at: datetime | None = None
    """When the reader last opened it (only in ``sort=recent`` lists)."""
    deleted_at: datetime | None
    processing: bool
    """Files are still being read (text, and metadata for uploads)."""
    tags: list[ItemTagOut]
    """Tags the reader can see: the library's own and the reader's private ones."""
    collection_ids: list[uuid.UUID]
    """Collections the reader can see that hold the item."""
    favourite: bool = False
    """The reader starred it."""


class ItemDetail(ItemOut):
    csl: dict[str, Any]
    """Metadata for citing: the preferred version's plus manual edits."""
    overrides: dict[str, Any]
    preferred_version_id: uuid.UUID | None
    versions: list[VersionOut]


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


def item_out(item: Item, access: Access) -> ItemOut:
    """The item as this person sees it: without other people's private tags
    and collections."""
    csl = library.citation_csl(item)
    return ItemOut(
        id=item.id,
        library_id=item.library_id,
        type=item.type,
        title=item.title,
        authors=library.author_names(csl),
        year=library.issued_year(csl),
        container_title=_container_title(csl),
        identifiers=[i for v in item.versions for i in _identifiers(v)],
        created_at=item.created_at,
        change=item.change,
        changed_at=item.changed_at,
        deleted_at=item.deleted_at,
        tags=item_tags(item, access),
        collection_ids=[
            link.collection_id
            for link in item.collection_links
            if access.can_read(link.collection.library_id)
        ],
        processing=any(
            f.text_status == TextStatus.PENDING and f.deleted_at is None
            for v in item.versions
            for f in v.files
        ),
        favourite=any(f.user_id == access.user.id for f in item.favourites),
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


def item_detail(
    item: Item, access: Access, response: Response | None = None
) -> ItemDetail:
    """The item; also sets its ``ETag`` (the change number) on ``response``."""
    if response is not None:
        response.headers["ETag"] = f'"{item.change}"'
    preferred = library.preferred_version(item)
    return ItemDetail(
        **item_out(item, access).model_dump(),
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


def add_or_find(
    db: Session, access: Access, http: httpx2.Client, body: ItemIn
) -> tuple[Item, bool]:
    """A new item, or the existing one if one of its identifiers is known
    among the items the person can see; and whether it is new."""
    library_id = access.target_library(body.library_id)
    identifiers = _normalized_identifiers(body)
    known = library.find_identifier(db, access.readable, identifiers)
    if known is not None:
        existing = known.version.item
        if existing.deleted_at is not None and access.can_write_item(existing):
            library.restore(existing)
            db.commit()
        return existing, False

    resolved = _resolve(body, identifiers, http)
    try:
        item = library.create_item(
            db,
            library_id,
            kind=resolved.kind,
            label=resolved.label,
            csl=resolved.csl,
            source=resolved.source,
            identifiers=resolved.identifiers,
            added_by=access.user.id,
        )
        db.commit()
    except IntegrityError:
        # Someone added the same identifier meanwhile.
        db.rollback()
        known = library.find_identifier(db, access.readable, identifiers)
        if known is None:
            raise
        return known.version.item, False
    except library.IdentifierTaken as error:
        # Added meanwhile; the lookup above missed it.
        raise _identifier_conflict(error) from error
    db.refresh(item)
    return item, True


@router.post("/api/items", status_code=201)
def add_item(
    body: ItemIn, request: Request, response: Response, db: DB, access: CurrentAccess
) -> ItemDetail:
    """A new item; if one of its identifiers is known among the items the
    person can see, the existing item (200)."""
    item, created = add_or_find(db, access, request.app.state.http, body)
    if not created:
        response.status_code = 200
    return item_detail(item, access, response)


def get_readable_item(
    db: DB,
    access: Access,
    item_id: uuid.UUID,
    *,
    write: bool = False,
    allow_trashed: bool = True,
) -> Item:
    """The item if the person may read it (404 otherwise, so items in other
    libraries stay unknown); with ``write``, 403 for readers."""
    item = db.get(Item, item_id)
    if item is None or not access.can_read_item(item):
        raise HTTPException(404, "item not found")
    if write:
        access.require_write_item(item)
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
    access: CurrentAccess,
) -> ItemDetail:
    """Another version of an item, e.g. the published one of a preprint."""
    item = get_readable_item(db, access, item_id, write=True, allow_trashed=False)
    identifiers = _normalized_identifiers(body)
    known = library.find_identifier(db, [item.library_id], identifiers)
    if known is not None:
        if known.version.item_id != item.id:
            raise _identifier_conflict(
                library.IdentifierTaken(
                    known.scheme, known.value, known.version.item_id, known.version_id
                )
            )
        response.status_code = 200
        return item_detail(item, access, response)

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
            created_by=access.user.id,
        )
        db.commit()
    except library.IdentifierTaken as error:
        raise _identifier_conflict(error) from error
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "identifier was added meanwhile") from error
    db.refresh(item)
    return item_detail(item, access, response)


@router.post("/api/versions/{version_id}/pin")
def pin_version(
    version_id: uuid.UUID, response: Response, db: DB, access: CurrentAccess
) -> ItemDetail:
    """Cite this version, whatever its kind."""
    version = db.get(Version, version_id)
    if version is None or not access.can_read_item(version.item):
        raise HTTPException(404, "version not found")
    access.require_write_item(version.item)
    library.pin_version(db, version.item, version)
    db.commit()
    return item_detail(version.item, access, response)


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
    access: CurrentAccess,
    if_match: Annotated[str | None, Header()] = None,
) -> ItemDetail:
    """Replace the manual edits to the metadata for citing.

    Fields set here win over every version's metadata and survive new
    lookups; ``null`` hides a field. Needs ``If-Match`` with the ETag from the
    last read, so concurrent edits are not lost (412 if the item changed).
    """
    expected = _parse_if_match(if_match)
    item = db.get(Item, item_id, with_for_update=True)
    if item is None or not access.can_read_item(item):
        raise HTTPException(404, "item not found")
    access.require_write_item(item)
    if item.change != expected:
        raise HTTPException(412, "item changed since it was read")
    library.set_overrides(item, overrides)
    db.commit()
    return item_detail(item, access, response)


@router.delete("/api/items/{item_id}", status_code=204)
def trash_item(item_id: uuid.UUID, db: DB, access: CurrentAccess) -> None:
    """Move to the trash; restorable with ``POST …/restore``."""
    library.trash(get_readable_item(db, access, item_id, write=True), access.user.id)
    db.commit()


class Owner(BaseModel):
    library_id: uuid.UUID
    """A person's or a group's library, see ``GET /api/libraries``."""


@router.put("/api/items/{item_id}/owner")
def set_owner(
    item_id: uuid.UUID,
    body: Owner,
    response: Response,
    db: DB,
    access: CurrentAccess,
) -> ItemDetail:
    """Give the item to another owner the person may add to: share it with a
    group, or take a group's paper for oneself (members may delete it
    anyway). Tags and collections of the group that gave it up come off."""
    item = get_readable_item(db, access, item_id, write=True, allow_trashed=False)
    access.target_library(body.library_id)
    library.set_owner(db, item, body.library_id)
    db.commit()
    return item_detail(item, access, response)


@router.post("/api/items/{item_id}/restore")
def restore_item(
    item_id: uuid.UUID, response: Response, db: DB, access: CurrentAccess
) -> ItemDetail:
    item = get_readable_item(db, access, item_id, write=True)
    library.restore(item)
    db.commit()
    return item_detail(item, access, response)


@router.get("/api/items")
def list_items(
    response: Response,
    db: DB,
    access: CurrentAccess,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: uuid.UUID | None = None,
    trashed: bool = False,
    since: Annotated[int | None, Query(ge=0)] = None,
    tag: Annotated[list[uuid.UUID] | None, Query()] = None,
    collection: uuid.UUID | None = None,
    nested: bool = True,
    title: Annotated[str | None, Query(max_length=200)] = None,
    library_id: Annotated[uuid.UUID | None, Query(alias="library")] = None,
    sort: Literal["added", "recent", "opened"] = "added",
    offset: Annotated[int, Query(ge=0)] = 0,
    unsorted: bool = False,
    favourite: bool = False,
    id: Annotated[list[uuid.UUID] | None, Query(max_length=200)] = None,
) -> list[ItemOut]:
    """Items the person can read, newest first; ``before`` = last ``id`` for
    the next page. ``library`` shows one library only. ``sort=recent``:
    by the latest of the item's last change and the reader's last opening,
    newest first, paged with ``offset`` instead of ``before``;
    ``sort=opened``: only items the reader opened, by when.

    ``trashed=true`` lists the trash instead. ``unsorted=true``: only papers
    with a PDF whose details could not be found (all guessed from the file;
    papers still being read, and notes or other files without a DOI to
    find, are left out). ``tag`` (repeatable: items
    with all of them) and ``collection`` (with its subcollections unless
    ``nested=false``) filter the list, and ``title`` to items with all of its
    words in their title (any case). ``X-Total-Count`` is the number of
    matching items, for showing the total while paging.
    ``since=N`` is for syncing:
    every item changed after change number N, trashed or not, in change
    order; ``limit`` and ``before`` do not apply. The ``Last-Change`` header
    is the number to pass as ``since`` next time.
    """
    response.headers["Last-Change"] = str(changes.current_change(db))
    libraries = access.readable
    if library_id is not None:
        libraries = [library_id] if access.can_read(library_id) else []
    in_libraries = access.item_filter(libraries)
    if since is not None:
        query = (
            select(Item)
            .where(in_libraries, Item.change > since)
            .order_by(Item.change, Item.id)
        )
        return [item_out(item, access) for item in db.scalars(query)]
    conditions = [
        in_libraries,
        Item.deleted_at.is_not(None) if trashed else Item.deleted_at.is_(None),
    ]
    for tag_id in tag or []:
        conditions.append(
            Item.id.in_(select(ItemTag.item_id).where(ItemTag.tag_id == tag_id))
        )
    if collection is not None:
        conditions.append(Item.id.in_(item_ids_in(db, collection, nested=nested)))
    for word in (title or "").split():
        conditions.append(Item.title.icontains(word, autoescape=True))
    if id:
        conditions.append(Item.id.in_(id))
    if favourite:
        conditions.append(
            Item.id.in_(
                select(Favourite.item_id).where(Favourite.user_id == access.user.id)
            )
        )
    if unsorted:
        conditions.append(
            Item.id.not_in(
                select(Version.item_id).where(
                    Version.metadata_source != MetadataSource.FILE
                )
            )
        )
        conditions.append(
            Item.id.not_in(
                select(Version.item_id)
                .join(File)
                .where(
                    File.text_status == TextStatus.PENDING, File.deleted_at.is_(None)
                )
            )
        )
        conditions.append(
            Item.id.in_(
                select(Version.item_id)
                .join(File)
                .where(File.media_type == "application/pdf", File.deleted_at.is_(None))
            )
        )
    total = db.scalar(select(func.count()).select_from(Item).where(*conditions)) or 0
    response.headers["X-Total-Count"] = str(total)
    if sort in ("recent", "opened"):
        viewed = (
            select(ItemView.item_id, ItemView.viewed_at)
            .where(ItemView.user_id == access.user.id)
            .subquery()
        )
        activity = (
            func.greatest(
                Item.changed_at, func.coalesce(viewed.c.viewed_at, Item.changed_at)
            )
            if sort == "recent"
            else viewed.c.viewed_at
        )
        if sort == "opened":
            conditions.append(viewed.c.viewed_at.is_not(None))
            opened_total = db.scalar(
                select(func.count())
                .select_from(Item)
                .join(viewed, viewed.c.item_id == Item.id)
                .where(*conditions)
            )
            response.headers["X-Total-Count"] = str(opened_total or 0)
        rows = db.execute(
            select(Item, viewed.c.viewed_at)
            .outerjoin(viewed, viewed.c.item_id == Item.id)
            .where(*conditions)
            .order_by(activity.desc(), Item.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [
            item_out(item, access).model_copy(update={"viewed_at": seen})
            for item, seen in rows
        ]
    query = select(Item).where(*conditions).order_by(Item.id.desc()).limit(limit)
    if before is not None:
        query = query.where(Item.id < before)
    return [item_out(item, access) for item in db.scalars(query)]


@router.put("/api/items/{item_id}/favourite", status_code=204)
def star_item(item_id: uuid.UUID, db: DB, access: CurrentAccess) -> Response:
    """Star the paper (for the person only; any paper they can see)."""
    get_readable_item(db, access, item_id)
    db.execute(
        insert(Favourite)
        .values(user_id=access.user.id, item_id=item_id)
        .on_conflict_do_nothing()
    )
    db.commit()
    return Response(status_code=204)


@router.delete("/api/items/{item_id}/favourite", status_code=204)
def unstar_item(item_id: uuid.UUID, db: DB, access: CurrentAccess) -> Response:
    get_readable_item(db, access, item_id)
    db.execute(
        delete(Favourite).where(
            Favourite.user_id == access.user.id, Favourite.item_id == item_id
        )
    )
    db.commit()
    return Response(status_code=204)


@router.post("/api/items/{item_id}/viewed", status_code=204)
def mark_viewed(item_id: uuid.UUID, db: DB, access: CurrentAccess) -> Response:
    """Remember that the person opened the item (for their recent papers)."""
    get_readable_item(db, access, item_id)
    db.execute(
        insert(ItemView)
        .values(user_id=access.user.id, item_id=item_id, viewed_at=func.now())
        .on_conflict_do_update(
            index_elements=[ItemView.user_id, ItemView.item_id],
            set_={"viewed_at": func.now()},
        )
    )
    db.commit()
    return Response(status_code=204)


@router.get("/api/items/{item_id}")
def get_item(
    item_id: uuid.UUID, response: Response, db: DB, access: CurrentAccess
) -> ItemDetail:
    return item_detail(get_readable_item(db, access, item_id), access, response)


@router.get("/api/items/{item_id}/duplicates")
def list_duplicates(item_id: uuid.UUID, db: DB, access: CurrentAccess) -> list[ItemOut]:
    """Papers the person can see that share an identifier or a file with
    this one: candidates for merging."""
    item = get_readable_item(db, access, item_id)
    return [
        item_out(other, access) for other in merge.likely_duplicates(db, access, item)
    ]


class MergeInto(BaseModel):
    into: uuid.UUID
    """The paper that stays; this one goes to the trash."""


class MergeStep(BaseModel):
    kind: merge.Kind
    name: str
    action: merge.Action
    """``move``: goes over; ``already``: the other paper has it; ``stays``:
    stays with the paper in the trash."""
    reason: str | None


class MergePreview(BaseModel):
    steps: list[MergeStep]


class MergeOut(MergePreview):
    item: ItemDetail
    """The paper that stayed, with what it took over."""


def _steps(steps: list[merge.Step]) -> list[MergeStep]:
    return [
        MergeStep(kind=s.kind, name=s.name, action=s.action, reason=s.reason)
        for s in steps
    ]


@router.get("/api/items/{item_id}/merge-preview")
def preview_merge(
    item_id: uuid.UUID,
    into: uuid.UUID,
    db: DB,
    access: CurrentAccess,
) -> MergePreview:
    """What merging this paper into ``into`` would move and leave behind."""
    source = get_readable_item(db, access, item_id, write=True, allow_trashed=False)
    target = get_readable_item(db, access, into, allow_trashed=False)
    try:
        return MergePreview(steps=_steps(merge.plan_merge(access, source, target, db)))
    except merge.CannotMerge as error:
        raise HTTPException(409, str(error)) from error


@router.post("/api/items/{item_id}/merge")
def merge_item(
    item_id: uuid.UUID,
    body: MergeInto,
    response: Response,
    db: DB,
    access: CurrentAccess,
) -> MergeOut:
    """Merge this paper into another one (the same paper twice). Needs the
    right to change this one; what may move to the other depends on the
    person's rights there (see docs/permissions.md)."""
    source = get_readable_item(db, access, item_id, write=True, allow_trashed=False)
    target = get_readable_item(db, access, body.into, allow_trashed=False)
    try:
        steps = merge.merge_items(db, access, source, target)
    except merge.CannotMerge as error:
        raise HTTPException(409, str(error)) from error
    db.commit()
    db.refresh(target)
    return MergeOut(item=item_detail(target, access, response), steps=_steps(steps))
