"""Notifications: what happened that concerns a person (mostly what they
did not do themselves), under the bell in the header. Papers added to one
of their groups (by upload, DOI, the extension, an import, or given to the
group: one notification per person who added and group, counted up while
unread for a few hours); a published version found for one of their
preprints (told apart where it is their own paper: they are among its
authors by their ORCID iD; their own paper is also told, to celebrate,
when it comes less than a week after it came out, however it comes and
whoever adds it); a paper new here citing one of their own (celebrated
too); a correction (erratum) found for one of their papers;
being added to a group by someone else (to a group of people: once it has
papers, else the papers' own notice says it); their own papers added from
OpenAlex by the daily job (to their library or a group's); each zip of their export as
it is written (or the export failing); and the end of their imports,
which may take long. Read ones go after ``KEEP_READ``, all after ``KEEP``
(the nightly tidy-up).

Papers reaching a group are noticed on the session (as ``details`` does),
so every way of adding them counts; the person who did it is the one who
added a new paper, or for a paper given to the group the one acting
(``db.info["paperus_actor"]``, set per request).
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from itertools import chain
from typing import Any

from sqlalchemy import delete, event, func, insert, inspect, or_, select, update
from sqlalchemy.orm import Session, UOWTransaction

from paperus.access import Access
from paperus.models import (
    Author,
    Authorship,
    Group,
    Identifier,
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
CITING_NEW = timedelta(days=30)
"""Only papers added this recently are told as citing one's own (older
ones would come all at once, when reference lists are looked for anew)."""
FRESH = timedelta(days=7)
"""A paper out less than this long ago, when it comes: one's own is
celebrated (``_fresh``)."""
ONE_NOTICE = timedelta(hours=6)
"""Papers added by the same person to the same group within this, while
unread, are one notification."""

ADDED = "added"
PUBLISHED = "published"
EXPORT = "export"
EXPORT_FAILED = "export_failed"
IMPORT = "import"
ERRATUM = "erratum"
JOINED = "joined"
OWN_ADDED = "own_added"
CITED = "cited"


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
                    "people": group.people,
                },
            )
        )


def published(db: Session, item: Item, version: Version) -> None:
    """A published version found for the paper: for everyone it concerns;
    for those among its authors as their own paper (once a paper)."""
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
    people = people_of(db, item.library_id)
    yours = _authors_here(db, item, people, [version])
    for user_id in people:
        db.add(
            Notification(
                user_id=user_id,
                kind=PUBLISHED,
                data={**data, "yours": True} if user_id in yours else data,
            )
        )


def _authors_here(
    db: Session, item: Item, people: list[uuid.UUID], versions: list[Version]
) -> set[uuid.UUID]:
    """Those of ``people`` among the paper's authors (by their ORCID iD),
    not yet told it is their own paper."""
    authors = _orcids(db, item, versions)
    if not authors:
        return set()
    told = select(Notification.user_id).where(
        Notification.kind == PUBLISHED,
        Notification.data["item_id"].astext == str(item.id),
        Notification.data["yours"].as_boolean(),
    )
    return set(
        db.scalars(
            select(User.id).where(
                User.id.in_(people), User.orcid.in_(authors), User.id.not_in(told)
            )
        )
    )


def cited(db: Session, citing: Item, dois: set[str], arxivs: set[str]) -> None:
    """A paper new in the library whose references (``dois``, ``arxivs``)
    name papers of people here (by their ORCID iDs): told to each of them
    who can read both, once a citing paper; not for their own papers."""
    added = citing.created_at
    if added is None or added < datetime.now(UTC) - CITING_NEW:
        return
    if not dois and not arxivs:
        return
    cited_ids = set(
        db.scalars(
            select(Version.item_id)
            .join(Identifier, Identifier.version_id == Version.id)
            .join(Item, Item.id == Version.item_id)
            .where(
                or_(
                    (Identifier.scheme == "doi") & Identifier.value.in_(dois),
                    (Identifier.scheme == "arxiv") & Identifier.value.in_(arxivs),
                ),
                Item.deleted_at.is_(None),
                Item.id != citing.id,
            )
        )
    )
    if not cited_ids:
        return
    own_authors = _orcids(db, citing, list(citing.versions))
    told = set(
        db.scalars(
            select(Notification.user_id).where(
                Notification.kind == CITED,
                Notification.data["item_id"].astext == str(citing.id),
            )
        )
    )
    yours: dict[uuid.UUID, list[Item]] = {}
    for item in db.scalars(select(Item).where(Item.id.in_(cited_ids))):
        authors = _orcids(db, item, list(item.versions)) - own_authors
        if not authors:
            continue
        for user in db.scalars(
            select(User).where(User.orcid.in_(authors), User.deactivated_at.is_(None))
        ):
            access = Access.of(db, user)
            if (
                user.id not in told
                and access.can_read_item(citing)
                and access.can_read_item(item)
            ):
                yours.setdefault(user.id, []).append(item)
    for user_id, items in yours.items():
        db.add(
            Notification(
                user_id=user_id,
                kind=CITED,
                data={
                    "item_id": str(citing.id),
                    "title": citing.title,
                    "cited_id": str(items[0].id),
                    "cited_title": items[0].title,
                    "count": len(items),
                },
            )
        )


def _fresh(db: Session, item: Item) -> None:
    """A paper out less than ``FRESH`` ago, by its exact date, now in a
    library: for those among its authors, their own paper published (also
    for whoever added it: it is to be celebrated)."""
    people = people_of(db, item.library_id)
    yours = _authors_here(db, item, people, list(item.versions))
    connection = db.connection()
    for user_id in yours:
        connection.execute(
            insert(Notification).values(
                user_id=user_id,
                kind=PUBLISHED,
                data={
                    "item_id": str(item.id),
                    "title": item.title,
                    "journal": item.journal,
                    "year": item.year,
                    "yours": True,
                    "fresh": True,
                },
            )
        )


_ORCID = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]")


def _orcids(db: Session, item: Item, versions: list[Version]) -> set[str]:
    """The ORCID iDs of the paper's authors: of the people linked to its
    authorships, the authorships' own, and the versions' author lists
    (before their authors are linked)."""
    found = set(
        db.scalars(
            select(Author.orcid)
            .join(Authorship, Authorship.author_id == Author.id)
            .where(Authorship.item_id == item.id, Author.orcid.is_not(None))
        )
    )
    found |= set(
        db.scalars(
            select(Authorship.orcid).where(
                Authorship.item_id == item.id, Authorship.orcid.is_not(None)
            )
        )
    )
    for version in versions:
        for author in version.csl.get("author") or []:
            if isinstance(author, dict) and (
                match := _ORCID.search(str(author.get("ORCID") or ""))
            ):
                found.add(match.group())
    return {orcid for orcid in found if orcid}


def erratum(db: Session, item: Item, cited: str) -> None:
    """A correction found for the paper (``errata``): for everyone it
    concerns; ``cited``: how it is cited ("Erratum: Phys. Rev. B 96, …")."""
    data = {"item_id": str(item.id), "title": item.title, "erratum": cited}
    for user_id in people_of(db, item.library_id):
        db.add(Notification(user_id=user_id, kind=ERRATUM, data=data))


def own_added(
    db: Session, user_id: uuid.UUID, library: Library, items: list[Item]
) -> None:
    """One's own papers added by the daily job (``own_papers``), to one's
    library or a group's (its other members are told as of any paper added
    to it)."""
    group = db.get(Group, library.group_id) if library.group_id else None
    db.add(
        Notification(
            user_id=user_id,
            kind=OWN_ADDED,
            data={
                "count": len(items),
                "item_id": str(items[0].id),
                "title": items[0].title,
                "library_id": str(library.id),
                "group": group.name if group else None,
            },
        )
    )


def _joined(db: Session, membership: Membership) -> None:
    group = db.get(Group, membership.group_id)
    who = db.get(User, membership.added_by) if membership.added_by else None
    if group is None or who is None:
        return
    connection = db.connection()
    library_id = connection.scalar(
        select(Library.id).where(Library.group_id == group.id)
    )
    papers = connection.scalar(
        select(func.count())
        .select_from(Item)
        .where(Item.library_id == library_id, Item.deleted_at.is_(None))
    )
    # A group of people just made for a paper: its paper's notice says it.
    if group.people and not papers:
        return
    connection.execute(
        insert(Notification).values(
            user_id=membership.user_id,
            kind=JOINED,
            data={
                "group_id": str(group.id),
                "library_id": str(library_id),
                "group": group.name,
                "people": group.people,
                "papers": papers or 0,
                "actor_id": str(who.id),
                "actor": who.display_name or who.username,
            },
        )
    )


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
                "own_copies": sum(report.get("own_copies", {}).values()),
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
    joined = db.info.setdefault("paperus_joined", [])
    fresh = db.info.setdefault("paperus_fresh", [])
    today = datetime.now(UTC).date()
    for obj in chain(db.new, db.dirty):
        # Out a few days ago (its exact day), new here or dated now.
        if (
            isinstance(obj, Item)
            and obj.issued_from is not None
            and obj.issued_from == obj.issued_to
            and today - FRESH <= obj.issued_from <= today + timedelta(days=1)
            and (obj in db.new or inspect(obj).attrs.issued_from.history.has_changes())
        ):
            fresh.append(obj)
    for obj in db.new:
        if isinstance(obj, Item) and obj.added_by is not None:
            pending.append((obj, obj.added_by))
        # Added to a group by someone else.
        if (
            isinstance(obj, Membership)
            and obj.added_by is not None
            and obj.added_by != obj.user_id
        ):
            joined.append(obj)
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
    joined: list[Membership] = db.info.pop("paperus_joined", [])
    fresh: list[Item] = db.info.pop("paperus_fresh", [])
    with db.no_autoflush:
        for membership in joined:
            _joined(db, membership)
        for item in fresh:
            if inspect(item).persistent and item.library_id is not None:
                _fresh(db, item)
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
    db.info.pop("paperus_joined", None)
    db.info.pop("paperus_fresh", None)
