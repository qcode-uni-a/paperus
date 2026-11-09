"""The log (``paperus.logbook``): read by administrators; the browser
extension reports its warnings and errors into it."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from paperus.api.admin import Admin
from paperus.api.deps import DB, CurrentUser
from paperus.models import LogEntry, User

router = APIRouter(tags=["logs"])

Level = Literal["debug", "info", "warning", "error", "critical"]
LEVELS: list[str] = ["debug", "info", "warning", "error", "critical"]


class LogEntryOut(BaseModel):
    id: int
    at: datetime
    level: str
    source: str
    """"server", "worker" or "extension"."""
    logger: str
    message: str
    username: str | None = None
    """Who reported it (the extension's entries)."""
    context: dict[str, Any] | None = None


class LogPage(BaseModel):
    entries: list[LogEntryOut]
    """Newest first."""
    more: bool
    """Older entries follow (``before`` the last one's id)."""


@router.get("/api/admin/logs")
def read_logs(
    db: DB,
    admin: Admin,
    level: Level = "info",
    source: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    before: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> LogPage:
    """The newest entries at ``level`` or above; ``source`` (repeatable)
    and words in the message (``q``) narrow them; ``before``: older than
    that entry."""
    query = (
        select(LogEntry, User.username)
        .outerjoin(User, User.id == LogEntry.user_id)
        .where(LogEntry.level.in_(LEVELS[LEVELS.index(level) :]))
        .order_by(LogEntry.id.desc())
        .limit(limit + 1)
    )
    if source:
        query = query.where(LogEntry.source.in_(source))
    if q and q.strip():
        query = query.where(LogEntry.message.icontains(q.strip(), autoescape=True))
    if before is not None:
        query = query.where(LogEntry.id < before)
    rows = db.execute(query).all()
    return LogPage(
        entries=[
            LogEntryOut(
                id=entry.id,
                at=entry.at,
                level=entry.level,
                source=entry.source,
                logger=entry.logger,
                message=entry.message,
                username=username,
                context=entry.context,
            )
            for entry, username in rows[:limit]
        ],
        more=len(rows) > limit,
    )


class ExtensionReport(BaseModel):
    level: Literal["info", "warning", "error"]
    message: str = Field(max_length=4000)
    at: datetime | None = None
    """When it happened (the extension sends its reports in batches)."""
    context: dict[str, str | int | float | bool | None] | None = Field(
        None, max_length=20
    )
    """E.g. the page and the PDF's address."""


class ExtensionReports(BaseModel):
    version: str = Field(max_length=32)
    """The extension's version."""
    entries: list[ExtensionReport] = Field(min_length=1, max_length=50)


@router.post("/api/logs", status_code=204)
def report(body: ExtensionReports, db: DB, user: CurrentUser) -> None:
    """The browser extension's warnings and errors, for the administrators
    (Administration → Logs), with who sent them."""
    now = datetime.now(UTC)
    for entry in body.entries:
        db.add(
            LogEntry(
                at=min(entry.at or now, now),
                level=entry.level,
                source="extension",
                logger=f"extension {body.version}",
                message=entry.message,
                user_id=user.id,
                context=entry.context,
            )
        )
    db.commit()
