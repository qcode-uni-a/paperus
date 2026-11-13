"""One change to many papers at once (the library's selection): each paper
as its own endpoint would change it, with the same rights; papers the
person may not change this way are skipped, with the reason."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from paperus import library, organize
from paperus.access import Access, Forbidden
from paperus.api.deps import DB, CurrentAccess
from paperus.api.items import ItemFilter, get_readable_item, item_conditions
from paperus.api.organize import Name, _collection, _not_smart, _tag
from paperus.models import Favourite, Item

router = APIRouter(tags=["items"])

MAX_ITEMS = 1000
# Papers a filter may match (a whole library, "Select all"): one request
# changes them all, each in its own savepoint.
MAX_MATCHING = 50_000


class Trash(BaseModel):
    kind: Literal["trash"]


class Restore(BaseModel):
    """Out of the trash."""

    kind: Literal["restore"]


class Archive(BaseModel):
    kind: Literal["archive"]


class Unarchive(BaseModel):
    kind: Literal["unarchive"]


class Star(BaseModel):
    kind: Literal["star"]


class Unstar(BaseModel):
    kind: Literal["unstar"]


class AddTag(BaseModel):
    kind: Literal["tag"]
    name: Name
    library_id: uuid.UUID | None = None
    """Whose tag, as for one paper (``POST /api/items/{id}/tags``): by
    default each paper's owner's if the person may change it, else their
    own."""


class RemoveTag(BaseModel):
    kind: Literal["untag"]
    tag_id: uuid.UUID


class AddToCollection(BaseModel):
    kind: Literal["collect"]
    collection_id: uuid.UUID


class RemoveFromCollection(BaseModel):
    kind: Literal["uncollect"]
    collection_id: uuid.UUID


class GiveTo(BaseModel):
    """To another owner the person may add to (see ``PUT
    /api/items/{id}/owner``)."""

    kind: Literal["owner"]
    library_id: uuid.UUID


Action = Annotated[
    Trash
    | Restore
    | Archive
    | Unarchive
    | Star
    | Unstar
    | AddTag
    | RemoveTag
    | AddToCollection
    | RemoveFromCollection
    | GiveTo,
    Field(discriminator="kind"),
]


class BulkIn(BaseModel):
    item_ids: list[uuid.UUID] | None = Field(None, min_length=1, max_length=MAX_ITEMS)
    matching: ItemFilter | None = None
    """Instead of ``item_ids``: every paper a list with these filters shows
    (``GET /api/items``), however many ("Select all")."""
    action: Action

    @model_validator(mode="after")
    def one_way(self) -> Self:
        if (self.item_ids is None) == (self.matching is None):
            raise ValueError("give item_ids or matching, one of them")
        return self


class Skipped(BaseModel):
    item_id: uuid.UUID
    reason: str


class BulkOut(BaseModel):
    done: list[uuid.UUID]
    """Changed, or as asked already."""
    skipped: list[Skipped]


@router.post("/api/items/bulk")
def bulk(body: BulkIn, db: DB, access: CurrentAccess) -> BulkOut:
    """Apply one action to each of the papers; those the person may not
    change so (or cannot see) are skipped with the reason, the others are
    changed together."""
    change = _change(db, access, body.action)
    item_ids = body.item_ids or _matching(db, access, body.matching)
    done: list[uuid.UUID] = []
    skipped: list[Skipped] = []
    for item_id in dict.fromkeys(item_ids):
        try:
            with db.begin_nested():
                change(item_id)
        except (HTTPException, Forbidden, ValueError) as error:
            reason = error.detail if isinstance(error, HTTPException) else str(error)
            skipped.append(Skipped(item_id=item_id, reason=reason))
        else:
            done.append(item_id)
    db.commit()
    return BulkOut(done=done, skipped=skipped)


def _matching(db: DB, access: Access, matching: ItemFilter | None) -> list[uuid.UUID]:
    """The papers the filter matches, oldest first; 413 for more than
    ``MAX_MATCHING``."""
    assert matching is not None
    found = list(
        db.scalars(
            select(Item.id)
            .where(*item_conditions(db, access, matching))
            .order_by(Item.id)
            .limit(MAX_MATCHING + 1)
        )
    )
    if len(found) > MAX_MATCHING:
        raise HTTPException(
            413, f"More than {MAX_MATCHING:,} papers match; filter the list further."
        )
    return found


def _change(db: DB, access: Access, action: Action) -> Callable[[uuid.UUID], None]:
    """What to do to one paper; checks that concern the action itself (the
    collection, the tag, the new owner) are made once, here."""

    def item(item_id: uuid.UUID, **rights: bool) -> Item:
        return get_readable_item(db, access, item_id, **rights)

    match action:
        case Trash():
            return lambda i: library.trash(item(i, write=True), access.user.id)
        case Restore():
            return lambda i: library.restore(item(i, write=True))
        case Archive():

            def archive(item_id: uuid.UUID) -> None:
                paper = item(item_id, write=True, allow_trashed=False)
                if paper.archived_at is None:
                    paper.archived_at = datetime.now(UTC)

            return archive
        case Unarchive():

            def unarchive(item_id: uuid.UUID) -> None:
                item(item_id, write=True).archived_at = None

            return unarchive
        case Star():

            def star(item_id: uuid.UUID) -> None:
                item(item_id)
                db.execute(
                    insert(Favourite)
                    .values(user_id=access.user.id, item_id=item_id)
                    .on_conflict_do_nothing()
                )

            return star
        case Unstar():

            def unstar(item_id: uuid.UUID) -> None:
                item(item_id)
                db.execute(
                    delete(Favourite).where(
                        Favourite.user_id == access.user.id,
                        Favourite.item_id == item_id,
                    )
                )

            return unstar
        case AddTag(name=name, library_id=chosen):
            if chosen is not None and not access.can_read(chosen):
                raise HTTPException(404, "library not found")

            def tag(item_id: uuid.UUID) -> None:
                paper = item(item_id)
                owner = chosen
                if owner is None:
                    writable = access.can_write(paper.library_id)
                    owner = paper.library_id if writable else access.own_library
                if not access.may_tag(owner, paper):
                    raise Forbidden("you may not change this item's tags")
                if organize.find_tag(db, owner, name) is None:
                    access.require_write(owner)  # new tags of a group: members
                organize.tag_item(
                    db, paper, name, library_id=owner, user_id=access.user.id
                )

            return tag
        case RemoveTag(tag_id=tag_id):
            removed = _tag(db, access, tag_id)

            def untag(item_id: uuid.UUID) -> None:
                paper = item(item_id)
                if not access.may_tag(removed.library_id, paper):
                    raise Forbidden("you may not change this item's tags")
                organize.untag_item(paper, tag_id)

            return untag
        case AddToCollection(collection_id=collection_id):
            target = _collection(db, access, collection_id, write=True)
            _not_smart(target)

            def collect(item_id: uuid.UUID) -> None:
                paper = item(item_id)
                if not access.may_hold(target.library_id, paper):
                    raise Forbidden(
                        "a group's collection holds only the group's papers"
                    )
                organize.add_to_collection(
                    db, target, [paper.id], access.user.id, may_hold=lambda _: True
                )

            return collect
        case RemoveFromCollection(collection_id=collection_id):
            source = _collection(db, access, collection_id, write=True)
            _not_smart(source)

            def uncollect(item_id: uuid.UUID) -> None:
                paper = item(item_id)
                paper.collection_links = [
                    link
                    for link in paper.collection_links
                    if link.collection_id != source.id
                ]

            return uncollect
        case GiveTo(library_id=library_id):
            access.target_library(library_id)

            def give(item_id: uuid.UUID) -> None:
                library.set_owner(
                    db, item(item_id, write=True, allow_trashed=False), library_id
                )

            return give
