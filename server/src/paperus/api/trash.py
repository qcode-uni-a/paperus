"""Emptying the trash by hand (the trash page)."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from paperus import trash
from paperus.api.deps import DB, CurrentAccess

router = APIRouter(tags=["trash"])


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
