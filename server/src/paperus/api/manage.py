"""What needs looking at, for the numbers next to Manage → Duplicates and
Unsorted in the menu."""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from paperus import duplicates
from paperus.api.deps import DB, CurrentAccess
from paperus.api.files import unreadable
from paperus.api.items import unsorted_conditions
from paperus.models import Item

router = APIRouter(tags=["manage"])


class ManageCounts(BaseModel):
    duplicates: int
    """Pairs that look like the same paper and are not decided yet."""
    unsorted: int
    """Papers whose details were only guessed from their file."""
    unreadable: int
    """Files whose text could not be read."""


@router.get("/api/manage/counts")
def manage_counts(db: DB, access: CurrentAccess) -> ManageCounts:
    """How many duplicates, unsorted papers and unreadable files the person
    can see."""
    unsorted = db.scalar(
        select(func.count())
        .select_from(Item)
        .where(
            access.item_filter(access.readable),
            Item.deleted_at.is_(None),
            *unsorted_conditions(),
        )
    )
    return ManageCounts(
        duplicates=len(duplicates.find(db, access)),
        unsorted=unsorted or 0,
        unreadable=len(unreadable(db, access)),
    )
