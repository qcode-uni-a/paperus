"""Likely duplicates across the library (Manage → Duplicates)."""

import uuid

from fastapi import APIRouter, Response
from pydantic import BaseModel

from paperus import duplicates
from paperus.access import Forbidden
from paperus.api.deps import DB, CurrentAccess
from paperus.api.items import ItemOut, get_readable_item, item_out

router = APIRouter(tags=["duplicates"])


class DuplicateOut(BaseModel):
    keep: ItemOut
    """The recommended paper to keep."""
    merge: ItemOut
    """The one to merge into it (it goes to the trash, restorable)."""
    reasons: list[str]
    """Why they look like the same paper: identifier, file, title."""
    why: list[str]
    """Why ``keep`` is recommended."""
    can_merge: bool
    """False if the person may change neither (a reader of both)."""


class Pair(BaseModel):
    a: uuid.UUID
    b: uuid.UUID


@router.get("/api/duplicates")
def list_duplicates_everywhere(db: DB, access: CurrentAccess) -> list[DuplicateOut]:
    """Pairs of papers that look like the same paper (same identifier or
    file first, then the same title), with a recommendation which to keep;
    pairs marked as different are left out."""
    return [
        DuplicateOut(
            keep=item_out(pair.keep, access),
            merge=item_out(pair.merge, access),
            reasons=pair.reasons,
            why=pair.why,
            can_merge=pair.can_merge,
        )
        for pair in duplicates.find(db, access)
    ]


@router.post("/api/duplicates/different", status_code=204)
def mark_different(body: Pair, db: DB, access: CurrentAccess) -> Response:
    """The two are different papers: do not suggest them again (for everyone
    who sees both). Needs the right to change at least one of them."""
    a = get_readable_item(db, access, body.a)
    b = get_readable_item(db, access, body.b)
    if not (access.can_write_item(a) or access.can_write_item(b)):
        raise Forbidden("readers cannot decide this for the group")
    duplicates.dismiss(db, body.a, body.b, access.user.id)
    db.commit()
    return Response(status_code=204)
