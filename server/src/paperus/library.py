"""Items, versions and identifiers: the rules that keep them consistent."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus.identifiers import Scheme
from paperus.metadata import csl_title, csl_type
from paperus.models import Identifier, Item, MetadataSource, Version, VersionKind

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

    def __init__(self, scheme: str, value: str, item_id: uuid.UUID) -> None:
        super().__init__(f"{scheme}:{value} belongs to item {item_id}")
        self.item_id = item_id


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
    db: Session, identifiers: list[IdentifierValue]
) -> Identifier | None:
    for scheme, value in identifiers:
        found = db.scalar(
            select(Identifier).where(
                Identifier.scheme == scheme, Identifier.value == value
            )
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
    taken = find_identifier(db, identifiers)
    if taken is not None:
        raise IdentifierTaken(taken.scheme, taken.value, taken.version.item_id)
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
    *,
    kind: VersionKind,
    label: str | None,
    csl: dict[str, Any],
    source: MetadataSource,
    identifiers: list[IdentifierValue],
    added_by: uuid.UUID | None,
) -> Item:
    """A new item with its first version."""
    item = Item(type="", title="", overrides={}, added_by=added_by)
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
