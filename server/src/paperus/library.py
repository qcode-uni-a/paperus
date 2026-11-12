"""Items, versions and identifiers: the rules that keep them consistent."""

import calendar
import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import changes  # noqa: F401  (registers the change stamping)
from paperus.identifiers import Scheme
from paperus.metadata import csl_title, csl_type
from paperus.models import (
    Identifier,
    Item,
    Library,
    LinkKind,
    MetadataSource,
    Trashable,
    Version,
    VersionKind,
)

# Which version is cited when none is pinned; newest first within a kind.
KIND_PREFERENCE = [
    VersionKind.PUBLISHED,
    VersionKind.ACCEPTED,
    VersionKind.EDITION,
    VersionKind.SUBMITTED,
    VersionKind.PREPRINT,
    VersionKind.DRAFT,
    VersionKind.OTHER,
]
_RANK = {kind.value: rank for rank, kind in enumerate(KIND_PREFERENCE)}

IdentifierValue = tuple[Scheme, str]


class IdentifierTaken(Exception):
    """An identifier already belongs to a version of an item."""

    def __init__(
        self, scheme: str, value: str, item_id: uuid.UUID, version_id: uuid.UUID
    ) -> None:
        super().__init__(f"{scheme}:{value} belongs to item {item_id}")
        self.item_id = item_id
        self.version_id = version_id


def preferred_version(item: Item) -> Version | None:
    return preferred_of(item.versions)


def preferred_of(versions: Sequence[Version]) -> Version | None:
    """The version whose details are shown: the pinned one (the first if
    several), else published before preprint before others, newest first."""
    for version in versions:
        if version.pinned:
            return version
    if not versions:
        return None
    newest_first = sorted(versions, key=lambda v: v.id, reverse=True)
    return min(newest_first, key=lambda v: _RANK[v.kind])


def citation_csl(item: Item) -> dict[str, Any]:
    """The preferred version's metadata with the item's manual edits
    applied; without an abstract, the one found for it (``paperus.abstracts``)."""
    version = preferred_version(item)
    csl = dict(version.csl) if version else {}
    for key, value in item.overrides.items():
        if value is None:
            csl.pop(key, None)
        else:
            csl[key] = value
    if item.abstract and "abstract" not in csl and "abstract" not in item.overrides:
        csl["abstract"] = item.abstract
    return csl


def author_names(csl: dict[str, Any]) -> list[str]:
    """ "Family, Given" for each author (or the literal name)."""
    names = []
    for author in csl.get("author", []):
        if "family" in author:
            names.append(
                ", ".join(filter(None, [author["family"], author.get("given")]))
            )
        elif "literal" in author:
            names.append(author["literal"])
    return names


def container_title(csl: dict[str, Any]) -> str | None:
    """The journal or venue (CSL's ``container-title``, a list in some)."""
    value = csl.get("container-title")
    if isinstance(value, list):
        value = value[0] if value else None
    return value.strip() or None if isinstance(value, str) else None


def issued_year(csl: dict[str, Any]) -> int | None:
    """The year of publication, from the first date there is."""
    for key in ("issued", "published-print", "published-online"):
        try:
            return int(csl[key]["date-parts"][0][0])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return None


def issued_range(csl: dict[str, Any]) -> tuple[date, date] | None:
    """The first and last day the publication date stands for: a day, a
    month or a year, as precisely as the first date there is gives it
    (a range of dates: from its start to its end)."""
    for key in ("issued", "published-print", "published-online"):
        try:
            parts = csl[key]["date-parts"]
            start = _day_range([int(p) for p in parts[0]])
            end = _day_range([int(p) for p in parts[-1]])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if start and end:
            return start[0], max(start[1], end[1])
    return None


def _day_range(parts: list[int]) -> tuple[date, date] | None:
    if not parts or not 1 <= parts[0] <= 9999:
        return None
    year = parts[0]
    month = parts[1] if len(parts) > 1 and 1 <= parts[1] <= 12 else None
    if month is None:
        return date(year, 1, 1), date(year, 12, 31)
    last = calendar.monthrange(year, month)[1]
    day = parts[2] if len(parts) > 2 and 1 <= parts[2] <= last else None
    if day is None:
        return date(year, month, 1), date(year, month, last)
    return date(year, month, day), date(year, month, day)


def authors_key(csl: dict[str, Any]) -> str:
    """A hash of the authors (names and ORCID iDs): when it changes, the
    paper's authors are linked to people again (``paperus.authors``)."""
    people = [
        [p.get(k) for k in ("family", "given", "literal", "ORCID")]
        for p in csl.get("author") or []
        if isinstance(p, dict)
    ]
    return hashlib.sha256(json.dumps(people, default=str).encode()).hexdigest()


def refresh_item(item: Item) -> None:
    """Update the cached type, title, year, dates, first author, journal
    and authors' key after versions or overrides change."""
    csl = citation_csl(item)
    item.authors_key = authors_key(csl)
    item.type = csl_type(csl)
    item.title = csl_title(csl)
    item.year = issued_year(csl)
    issued = issued_range(csl)
    item.issued_from, item.issued_to = issued or (None, None)
    item.first_author = next((name for name in author_names(csl) if name), None)
    item.journal = container_title(csl)


def find_identifier(
    db: Session, libraries: list[uuid.UUID], identifiers: list[IdentifierValue]
) -> Identifier | None:
    """An identifier among these that a version of an item in one of the
    libraries already has (those the person can read: a paper in someone
    else's private library stays unknown to them)."""
    for scheme, value in identifiers:
        found = db.scalar(
            select(Identifier)
            .join(Version)
            .join(Item)
            .where(
                Identifier.scheme == scheme,
                Identifier.value == value,
                Item.library_id.in_(libraries),
            )
            .order_by(Identifier.id)
            .limit(1)
        )
        if found is not None:
            return found
    return None


def add_version(
    db: Session,
    item: Item,
    *,
    kind: VersionKind,
    label: str | None,
    csl: dict[str, Any],
    source: MetadataSource,
    identifiers: list[IdentifierValue],
    created_by: uuid.UUID | None,
) -> Version:
    taken = find_identifier(db, [item.library_id], identifiers)
    if taken is not None:
        raise IdentifierTaken(
            taken.scheme, taken.value, taken.version.item_id, taken.version_id
        )
    version = Version(
        kind=kind,
        label=label,
        csl={**csl, "type": csl_type(csl)},
        metadata_source=source,
        created_by=created_by,
        identifiers=[
            Identifier(scheme=scheme, value=value)
            for scheme, value in dict.fromkeys(identifiers)
        ],
    )
    item.versions.append(version)
    db.flush()
    refresh_item(item)
    return version


def create_item(
    db: Session,
    library_id: uuid.UUID,
    *,
    kind: VersionKind,
    label: str | None,
    csl: dict[str, Any],
    source: MetadataSource,
    identifiers: list[IdentifierValue],
    added_by: uuid.UUID | None,
) -> Item:
    """A new item in the library, with its first version."""
    item = Item(
        library_id=library_id,
        type="",
        title="",
        overrides={},
        added_by=added_by,
        change=0,
    )
    db.add(item)
    add_version(
        db,
        item,
        kind=kind,
        label=label,
        csl=csl,
        source=source,
        identifiers=identifiers,
        created_by=added_by,
    )
    return item


def pin_version(db: Session, item: Item, version: Version) -> None:
    for other in item.versions:
        other.pinned = False
    # Unpin first: at most one pinned version per item (unique index).
    db.flush()
    version.pinned = True
    refresh_item(item)


def _link_key(url: str) -> str:
    """The same address, written a little differently, is the same link."""
    return url.strip().rstrip("/").removeprefix("https://").removeprefix("http://")


def add_links(item: Item, links: Sequence[dict[str, Any]]) -> bool:
    """Add links (``{"url", "kind", "label"}``) the item has not got yet; one
    it has keeps its kind and label unless the new one names them (a
    person's choice over a guess: ``replace``). Returns whether any was
    new."""
    current = [dict(link) for link in item.links]
    known = {_link_key(link["url"]): link for link in current}
    added = False
    for link in links:
        url = str(link["url"]).strip()
        if (same := known.get(_link_key(url))) is None:
            entry = {
                "url": url,
                "kind": str(link.get("kind") or LinkKind.OTHER),
                "label": link.get("label") or None,
            }
            current.append(entry)
            known[_link_key(url)] = entry
            added = True
        elif link.get("replace"):
            same["kind"] = str(link.get("kind") or same["kind"])
            same["label"] = link.get("label") or None
    if current != item.links:
        # A new list: SQLAlchemy does not see changes inside JSON.
        item.links = current
    return added


def remove_link(item: Item, url: str) -> bool:
    """Take a link off; whether it was there."""
    kept = [link for link in item.links if _link_key(link["url"]) != _link_key(url)]
    if len(kept) == len(item.links):
        return False
    item.links = kept
    return True


def set_overrides(item: Item, overrides: dict[str, Any]) -> None:
    """Replace the manual edits; ``None`` hides a field from citations."""
    item.overrides = overrides
    refresh_item(item)


def trash(obj: Trashable, user_id: uuid.UUID | None) -> None:
    if obj.deleted_at is None:
        obj.deleted_at = datetime.now(UTC)
        obj.deleted_by = user_id


def restore(obj: Trashable) -> None:
    obj.deleted_at = None
    obj.deleted_by = None


def replace_metadata(
    db: Session,
    version: Version,
    *,
    kind: VersionKind,
    csl: dict[str, Any],
    source: MetadataSource,
    identifiers: list[IdentifierValue],
    known_in: list[uuid.UUID] | None = None,
) -> None:
    """Give a version new metadata and identifiers (e.g. found in its file).

    ``IdentifierTaken`` if an item in the libraries ``known_in`` (default:
    the item's own) already has one of them.
    """
    libraries = [version.item.library_id] if known_in is None else known_in
    taken = find_identifier(db, libraries, identifiers)
    if taken is not None and taken.version_id != version.id:
        raise IdentifierTaken(
            taken.scheme, taken.value, taken.version.item_id, taken.version_id
        )
    known = {(i.scheme, i.value) for i in version.identifiers}
    version.identifiers.extend(
        Identifier(scheme=scheme, value=value)
        for scheme, value in dict.fromkeys(identifiers)
        if (scheme, value) not in known
    )
    version.kind = kind
    version.csl = {**csl, "type": csl_type(csl)}
    version.metadata_source = source
    db.flush()
    refresh_item(version.item)


def set_owner(db: Session, item: Item, library_id: uuid.UUID) -> None:
    """Give the item to another owner (a person's or a group's library). The
    collections of a group that no longer owns it let it go (a group's
    collections hold only its papers); tags stay."""
    if item.library_id == library_id:
        return
    item.library_id = library_id
    held = {link.collection.library_id for link in item.collection_links}
    groups = set(
        db.scalars(
            select(Library.id).where(
                Library.id.in_(held), Library.group_id.is_not(None)
            )
        )
    )
    gone = groups - {library_id}
    item.collection_links = [
        link for link in item.collection_links if link.collection.library_id not in gone
    ]
