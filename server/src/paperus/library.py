"""Items, versions and identifiers: the rules that keep them consistent."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import changes  # noqa: F401  (registers the change stamping)
from paperus.identifiers import Scheme
from paperus.metadata import csl_title, csl_type
from paperus.models import (
    Identifier,
    Item,
    ItemLibrary,
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
    for version in item.versions:
        if version.pinned:
            return version
    if not item.versions:
        return None
    newest_first = sorted(item.versions, key=lambda v: v.id, reverse=True)
    return min(newest_first, key=lambda v: _RANK[v.kind])


def citation_csl(item: Item) -> dict[str, Any]:
    """The preferred version's metadata with the item's manual edits applied."""
    version = preferred_version(item)
    csl = dict(version.csl) if version else {}
    for key, value in item.overrides.items():
        if value is None:
            csl.pop(key, None)
        else:
            csl[key] = value
    return csl


def refresh_item(item: Item) -> None:
    """Update the cached type and title after versions or overrides change."""
    csl = citation_csl(item)
    item.type = csl_type(csl)
    item.title = csl_title(csl)


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
            .where(
                Identifier.scheme == scheme,
                Identifier.value == value,
                Version.item_id.in_(
                    select(ItemLibrary.item_id).where(
                        ItemLibrary.library_id.in_(libraries)
                    )
                ),
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
    taken = find_identifier(db, item.library_ids, identifiers)
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
        library_links=[ItemLibrary(library_id=library_id, added_by=added_by)],
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
    libraries = version.item.library_ids if known_in is None else known_in
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


def add_to_library(
    item: Item, library_id: uuid.UUID, user_id: uuid.UUID | None
) -> bool:
    """Put the item into another library too (sharing it); False if it was
    there already."""
    if library_id in item.library_ids:
        return False
    item.library_links.append(ItemLibrary(library_id=library_id, added_by=user_id))
    return True


def remove_from_library(
    item: Item, library_id: uuid.UUID, user_id: uuid.UUID | None
) -> None:
    """Take the item out of one library; out of the last one, it goes to the
    trash instead (and keeps that library, for restoring)."""
    if library_id not in item.library_ids:
        return
    if len(item.library_links) == 1:
        trash(item, user_id)
        return
    item.library_links = [
        link for link in item.library_links if link.library_id != library_id
    ]
    # Its tags and collections of that library no longer apply.
    item.tag_links = [
        link for link in item.tag_links if link.tag.library_id != library_id
    ]
    item.collection_links = [
        link
        for link in item.collection_links
        if link.collection.library_id != library_id
    ]
