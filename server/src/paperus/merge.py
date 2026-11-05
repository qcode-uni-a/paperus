"""Merging two items that are the same paper (duplicates).

The merged-away item goes to the trash (restorable); the other one keeps
its details and takes over what it may: versions and files (only if the
person may change it), tags and collections (where the rules of
``paperus.access`` allow). Nothing happens automatically: people choose.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import library
from paperus.access import Access
from paperus.models import (
    CollectionItem,
    File,
    FileRole,
    Identifier,
    Item,
    ItemTag,
    Version,
)


class CannotMerge(ValueError):
    pass


@dataclass
class MergeResult:
    versions: int = 0
    """Versions moved over (e.g. a preprint to the published paper)."""
    files: int = 0
    """Files moved over (those the target did not have)."""
    tags: int = 0
    collections: int = 0
    left_behind: list[str] = field(default_factory=list)
    """What could not move (it stays with the trashed item)."""


def likely_duplicates(db: Session, access: Access, item: Item) -> list[Item]:
    """Items the person can see that share an identifier or a file with this
    one: the likely same paper."""
    pairs = [(i.scheme, i.value) for v in item.versions for i in v.identifiers]
    blobs = [
        f.blob_sha256 for v in item.versions for f in v.files if f.deleted_at is None
    ]
    found: dict[uuid.UUID, Item] = {}
    candidates = select(Item).where(
        Item.id != item.id, Item.deleted_at.is_(None), access.item_filter()
    )
    for scheme, value in pairs:
        query = (
            candidates.join(Version)
            .join(Identifier)
            .where(Identifier.scheme == scheme, Identifier.value == value)
        )
        for other in db.scalars(query).unique():
            found[other.id] = other
    if blobs:
        query = (
            candidates.join(Version)
            .join(File)
            .where(File.blob_sha256.in_(blobs), File.deleted_at.is_(None))
        )
        for other in db.scalars(query).unique():
            found[other.id] = other
    return list(found.values())


def _identifiers(version: Version) -> set[tuple[str, str]]:
    return {(i.scheme, i.value) for i in version.identifiers}


def _move_files(source: Version, target: Version) -> int:
    """Files of ``source`` that ``target`` lacks (by content) move over."""
    moved = 0
    for file in list(source.files):
        live = [f for f in target.files if f.deleted_at is None]
        if file.deleted_at is not None or any(
            f.blob_sha256 == file.blob_sha256 for f in live
        ):
            continue
        has_main = any(f.role == FileRole.MAIN for f in live)
        if file.role == FileRole.MAIN and has_main:
            file.role = FileRole.OTHER
        file.version = target
        moved += 1
    return moved


def merge_items(db: Session, access: Access, source: Item, target: Item) -> MergeResult:
    """Merge ``source`` into ``target`` and put ``source`` in the trash."""
    if source.id == target.id:
        raise CannotMerge("a paper cannot be merged into itself")
    if target.deleted_at is not None:
        raise CannotMerge("the other paper is in the trash")
    result = MergeResult()
    if access.can_write_item(target):
        for version in list(source.versions):
            same = next(
                (v for v in target.versions if _identifiers(v) & _identifiers(version)),
                None,
            )
            if same is not None:
                result.files += _move_files(version, same)
            else:
                if version.pinned and any(v.pinned for v in target.versions):
                    version.pinned = False
                version.item = target
                result.versions += 1
        db.flush()
        library.refresh_item(target)
    else:
        result.left_behind.append(
            "versions and files (you may not change the other paper)"
        )

    tagged = {link.tag_id for link in target.tag_links}
    for link in source.tag_links:
        if link.tag_id in tagged:
            continue
        if access.may_tag(link.tag.library_id, target):
            target.tag_links.append(
                ItemTag(
                    tag_id=link.tag_id,
                    tag=link.tag,
                    source=link.source,
                    added_by=access.user.id,
                )
            )
            result.tags += 1
        elif access.can_read(link.tag.library_id):
            result.left_behind.append(f"tag “{link.tag.name}”")
    held = {link.collection_id for link in target.collection_links}
    for link in source.collection_links:
        collection = link.collection
        if link.collection_id in held or not access.can_read(collection.library_id):
            continue
        if access.can_write(collection.library_id) and access.may_hold(
            collection.library_id, target
        ):
            target.collection_links.append(
                CollectionItem(collection_id=collection.id, added_by=access.user.id)
            )
            result.collections += 1
        else:
            result.left_behind.append(f"collection “{collection.name}”")
    library.trash(source, access.user.id)
    db.flush()
    return result
