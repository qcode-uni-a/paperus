"""Notifications: what happened that concerns a person and that they did
not do themselves, under the bell in the header. Papers added to one of
their groups (by upload, DOI, the extension, an import, or given to the
group: one notification per person who added and group, counted up while
unread for a few hours), a published version found for one of their
preprints, each zip of their export as it is written (or the export
failing), and the end of their imports, which may take long. Read ones go
after ``KEEP_READ``, all after ``KEEP`` (the
nightly tidy-up).

Papers reaching a group are noticed on the session (as ``details`` does),
so every way of adding them counts; the person who did it is the one who
added a new paper, or for a paper given to the group the one acting
(``db.info["paperus_actor"]``, set per request).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, event, func, insert, inspect, or_, select, update
from sqlalchemy.orm import Session, UOWTransaction

from paperus.models import (
    Group,
    Import,
    ImportStatus,
    Item,
    Library,
    Membership,
    Notification,
    User,
    Version,
)

KEEP_READ = timedelta(days=30)
KEEP = timedelta(days=90)
ONE_NOTICE = timedelta(hours=6)
"""Papers added by the same person to the same group within this, while
unread, are one notification."""

ADDED = "added"
PUBLISHED = "published"
EXPORT = "export"
EXPORT_FAILED = "export_failed"
IMPORT = "import"


def people_of(db: Session, library_id: uuid.UUID) -> list[uuid.UUID]:
    """Whom a library's papers concern: its person, or everyone in its
    group (given a role there or in a group above)."""
    library = db.get(Library, library_id)
    if library is None:
        return []
    if library.user_id is not None:
        return [library.user_id]
    chain: list[uuid.UUID] = []
    group = db.get(Group, library.group_id)
    while group is not None:
        chain.append(group.id)
        group = db.get(Group, group.parent_id) if group.parent_id else None
    return list(
        db.scalars(
            select(Membership.user_id).where(Membership.group_id.in_(chain)).distinct()
        )
    )


def _added(
    db: Session, library_id: uuid.UUID, actor: uuid.UUID, items: list[Item]
) -> None:
    library = db.get(Library, library_id)
    if library is None or library.group_id is None:
        return
    group = db.get(Group, library.group_id)
    who = db.get(User, actor)
    if group is None or who is None:
        return
    connection = db.connection()
    since = datetime.now(UTC) - ONE_NOTICE
    first = items[0]
    for user_id in people_of(db, library_id):
        if user_id == actor:
            continue
        known = connection.execute(
            select(Notification.id, Notification.data).where(
                Notification.user_id == user_id,
                Notification.kind == ADDED,
                Notification.read_at.is_(None),
                Notification.at >= since,
                Notification.data["library_id"].astext == str(library_id),
                Notification.data["actor_id"].astext == str(actor),
            )
        ).first()
        if known is not None:
            data = {**known.data, "count": known.data.get("count", 1) + len(items)}
            connection.execute(
                update(Notification)
                .where(Notification.id == known.id)
                .values(data=data, at=func.now())
            )
            continue
        connection.execute(
            insert(Notification).values(
                user_id=user_id,
                kind=ADDED,
                data={
                    "library_id": str(library_id),
                    "group": group.name,
                    "actor_id": str(actor),
                    "actor": who.display_name or who.username,
                    "count": len(items),
                    "item_id": str(first.id),
                    "title": first.title,
                },
            )
        )


def published(db: Session, item: Item, version: Version) -> None:
    """A published version found for the paper: for everyone it concerns."""
    csl: dict[str, Any] = version.csl
    journal = csl.get("container-title")
    if isinstance(journal, list):
        journal = journal[0] if journal else None
    issued = (csl.get("issued") or {}).get("date-parts") or [[None]]
    data = {
        "item_id": str(item.id),
        "title": item.title,
        "journal": journal,
        "year": issued[0][0] if issued and issued[0] else None,
    }
    for user_id in people_of(db, item.library_id):
        db.add(Notification(user_id=user_id, kind=PUBLISHED, data=data))


def export_ready(
    db: Session, user_id: uuid.UUID, export_id: uuid.UUID, part: int, parts: int
) -> None:
    """A zip of the person's export is written (the last: all are)."""
    db.add(
        Notification(
            user_id=user_id,
            kind=EXPORT,
            data={"export_id": str(export_id), "part": part, "parts": parts},
        )
    )


def export_failed(db: Session, user_id: uuid.UUID, export_id: uuid.UUID) -> None:
    db.add(
        Notification(
            user_id=user_id, kind=EXPORT_FAILED, data={"export_id": str(export_id)}
        )
    )


def import_finished(db: Session, record: Import) -> None:
    """An import has ended (it may take long): what came of it, in short."""
    report = record.report or {}
    db.add(
        Notification(
            user_id=record.user_id,
            kind=IMPORT,
            data={
                "import_id": str(record.id),
                "filename": record.filename,
                "failed": record.status == ImportStatus.FAILED,
                "added": report.get("added", 0),
                "found": report.get("found", 0),
                "found_elsewhere": sum(report.get("found_elsewhere", {}).values()),
                "files_not_added": sum(report.get("files_not_added", {}).values()),
                "problems": len(report.get("problems", []))
                + len(report.get("missing_files", [])),
            },
        )
    )


def prune(db: Session, now: datetime | None = None) -> int:
    """Delete read notifications older than ``KEEP_READ`` and all older
    than ``KEEP``; how many went."""
    now = now or datetime.now(UTC)
    result = db.execute(
        delete(Notification).where(
            or_(
                Notification.at < now - KEEP,
                (Notification.read_at.is_not(None))
                & (Notification.at < now - KEEP_READ),
            )
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


@event.listens_for(Session, "before_flush")
def _note_additions(db: Session, flush: UOWTransaction, instances: object) -> None:
    """Papers new in a library, or given to another: noted, with who did it."""
    pending = db.info.setdefault("paperus_added", [])
    for obj in db.new:
        if isinstance(obj, Item) and obj.added_by is not None:
            pending.append((obj, obj.added_by))
    actor = db.info.get("paperus_actor")
    if actor is None:
        return
    for obj in db.dirty:
        if (
            isinstance(obj, Item)
            and inspect(obj).attrs.library_id.history.has_changes()
        ):
            pending.append((obj, actor))


@event.listens_for(Session, "after_flush_postexec")
def _notify_additions(db: Session, flush: UOWTransaction) -> None:
    pending: list[tuple[Item, uuid.UUID]] = db.info.pop("paperus_added", [])
    batches: dict[tuple[uuid.UUID, uuid.UUID], list[Item]] = {}
    for item, actor in pending:
        if inspect(item).persistent and item.library_id is not None:
            batches.setdefault((item.library_id, actor), []).append(item)
    with db.no_autoflush:
        for (library_id, actor), items in batches.items():
            _added(db, library_id, actor, items)


@event.listens_for(Session, "after_rollback")
def _forget(db: Session) -> None:
    db.info.pop("paperus_added", None)
