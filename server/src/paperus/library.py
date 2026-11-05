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
    db: Session, library_id: uuid.UUID, identifiers: list[IdentifierValue]
) -> Identifier | None:
    """An identifier among these that a version in the library already has."""
    for scheme, value in identifiers:
        found = db.scalar(
            select(Identifier)
            .join(Version)
            .join(Item)
            .where(
                Identifier.scheme == scheme,
                Identifier.value == value,
                Item.library_id == library_id,
            )
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
    taken = find_identifier(db, item.library_id, identifiers)
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
) -> None:
    """Give a version new metadata and identifiers (e.g. found in its file)."""
    taken = find_identifier(db, version.item.library_id, identifiers)
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
