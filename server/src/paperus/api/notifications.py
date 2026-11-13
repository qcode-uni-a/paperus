"""The person's notifications (``paperus.notifications``), under the bell
in the header."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from paperus.api.deps import DB, SessionUser
from paperus.models import Item, Notification

router = APIRouter(prefix="/api/me/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: int
    kind: str
    """"added": papers added to a group (``data``: group, library_id,
    actor, count, item_id and title of the first); "published": a
    published version found (item_id, title, journal, year); "export": a
    zip of one's export written (export_id, part, parts; the last part:
    the export is done); "export_failed": the export failed (export_id);
    "import": an import ended (import_id, filename, failed, and the
    report's added, found, found_elsewhere, own_copies and problems, the
    last three as totals)."""
    data: dict[str, Any]
    at: datetime
    read: bool


class Notifications(BaseModel):
    notifications: list[NotificationOut]
    """Newest first."""
    unread: int


@router.get("")
def list_notifications(
    db: DB, user: SessionUser, limit: Annotated[int, Query(ge=1, le=100)] = 30
) -> Notifications:
    found = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.at.desc(), Notification.id.desc())
        .limit(limit)
    )
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    notices = list(found)
    # The paper's title as it is now (empty while a new upload was being
    # read when the notification was made; edited since).
    ids = {uuid.UUID(n.data["item_id"]) for n in notices if n.data.get("item_id")}
    titles = {
        item_id: title
        for item_id, title in db.execute(
            select(Item.id, Item.title).where(Item.id.in_(ids))
        )
    }
    return Notifications(
        notifications=[
            NotificationOut(
                id=n.id,
                kind=n.kind,
                data=_titled(n.data, titles),
                at=n.at,
                read=n.read_at is not None,
            )
            for n in notices
        ],
        unread=unread or 0,
    )


def _titled(data: dict[str, Any], titles: dict[uuid.UUID, str]) -> dict[str, Any]:
    item_id = data.get("item_id")
    title = titles.get(uuid.UUID(item_id)) if item_id else None
    return {**data, "title": title} if title else data


class Read(BaseModel):
    ids: list[int] | None = Field(None, max_length=500)
    """These; all of the person's if not given."""


@router.post("/read", status_code=204)
def mark_notifications_read(body: Read, db: DB, user: SessionUser) -> Response:
    query = update(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)
    )
    if body.ids is not None:
        query = query.where(Notification.id.in_(body.ids))
    db.execute(query.values(read_at=func.now()))
    db.commit()
    return Response(status_code=204)
