"""The trash page (when its contents go, emptying it by hand), and how full
the storage is (the menu)."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from paperus import trash
from paperus.api.deps import DB, CurrentAccess
from paperus.system import load_config

router = APIRouter(tags=["trash"])


class TrashRules(BaseModel):
    days: int | None
    """What is in the trash is deleted for good after this many days, at
    half past the night hour; None: it stays until emptied by hand."""
    night_hour: int
    """Hour (UTC) of the nightly emptying."""


@router.get("/api/trash")
def trash_rules(request: Request, db: DB, access: CurrentAccess) -> TrashRules:
    """When the trash is emptied by itself (Administration → Settings)."""
    config = load_config(db, request.app.state.settings)
    return TrashRules(days=config.trash_days, night_hour=config.night_hour)


class Emptied(BaseModel):
    items: int
    notes: int
    files: int


@router.delete("/api/trash")
def empty_trash(request: Request, db: DB, access: CurrentAccess) -> Emptied:
    """Delete for good everything in the trash the person may change: their
    own and that of groups where they are a member or admin."""
    done = trash.empty(db, request.app.state.blobs, libraries=access.writable)
    return Emptied(items=done.items, notes=done.notes, files=done.files)
