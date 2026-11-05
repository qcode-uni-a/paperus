"""Merging two items that are the same paper (duplicates).

The merged-away item goes to the trash (restorable); the other one keeps
its details and takes over what it may: versions and files (only if the
person may change it), tags and collections (where the rules of
``paperus.access`` allow). Nothing happens automatically: people choose.

``plan_merge`` decides, step by step, what moves and what stays behind and
why; a preview shows that plan, and ``merge_items`` carries out the same
plan, so the two never disagree.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import delete, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import library
from paperus.access import Access
from paperus.models import (
    CollectionItem,
    Favourite,
    File,
    FileRole,
    Identifier,
    Item,
    ItemTag,
    Note,
    NoteItem,
    Version,
)

Kind = Literal["version", "file", "tag", "collection", "note"]
Action = Literal["move", "already", "stays"]


class CannotMerge(ValueError):
    pass


@dataclass
class Step:
    kind: Kind
    name: str
    action: Action
    reason: str | None = None
    """Why it stays behind, or what it already matches."""
    apply: Callable[[], None] | None = None


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


def _version_name(version: Version) -> str:
    """ "Preprint: doi 10.48550/…", "Edition (WS 2026/27)", or "Version
    without identifier"."""
    kind = "Version" if version.kind == "other" else version.kind.capitalize()
    label = f"{kind}{f' ({version.label})' if version.label else ''}"
    ids = ", ".join(f"{i.scheme} {i.value}" for i in version.identifiers)
    return f"{label}: {ids}" if ids else f"{label} without identifier"


def _move_file(file: File, target: Version) -> None:
    live = [f for f in target.files if f.deleted_at is None]
    if file.role == FileRole.MAIN and any(f.role == FileRole.MAIN for f in live):
        file.role = FileRole.OTHER
    file.version = target


def _move_version(version: Version, target: Item) -> None:
    if version.pinned and any(v.pinned for v in target.versions):
        version.pinned = False
    version.item = target


def plan_merge(
    access: Access, source: Item, target: Item, db: Session | None = None
) -> list[Step]:
    """What merging ``source`` into ``target`` does, step by step (with
    ``db``, also the notes the person can see)."""
    if source.id == target.id:
        raise CannotMerge("a paper cannot be merged into itself")
    if target.deleted_at is not None:
        raise CannotMerge("the other paper is in the trash")
    steps: list[Step] = []
    writable = access.can_write_item(target)
    not_yours = "you may not change the other paper"
    for version in source.versions:
        files = [f for f in version.files if f.deleted_at is None]
        same = next(
            (v for v in target.versions if _identifiers(v) & _identifiers(version)),
            None,
        )
        if same is None:
            steps.append(
                Step(
                    "version",
                    _version_name(version),
                    "move" if writable else "stays",
                    None if writable else not_yours,
                    (lambda v=version: _move_version(v, target)) if writable else None,
                )
            )
            # Its files go along with it.
            steps.extend(
                Step(
                    "file",
                    f.filename,
                    "move" if writable else "stays",
                    None if writable else not_yours,
                )
                for f in files
            )
            continue
        steps.append(
            Step("version", _version_name(version), "already", "the same version")
        )
        have = {f.blob_sha256 for f in same.files if f.deleted_at is None}
        for file in files:
            if file.blob_sha256 in have:
                steps.append(Step("file", file.filename, "already", "the same file"))
            elif writable:
                steps.append(
                    Step(
                        "file",
                        file.filename,
                        "move",
                        apply=lambda f=file, to=same: _move_file(f, to),
                    )
                )
            else:
                steps.append(Step("file", file.filename, "stays", not_yours))

    tagged = {link.tag_id for link in target.tag_links}
    for link in source.tag_links:
        tag = link.tag
        if not access.can_read(tag.library_id):
            continue  # someone else's private tag
        if link.tag_id in tagged:
            steps.append(Step("tag", tag.name, "already"))
        elif access.may_tag(tag.library_id, target):
            steps.append(
                Step(
                    "tag",
                    tag.name,
                    "move",
                    apply=lambda t=tag, s=link.source: target.tag_links.append(
                        ItemTag(tag_id=t.id, tag=t, source=s, added_by=access.user.id)
                    ),
                )
            )
        else:
            steps.append(
                Step(
                    "tag",
                    tag.name,
                    "stays",
                    "a group's tags go only on papers you may change",
                )
            )
    held = {link.collection_id for link in target.collection_links}
    for link in source.collection_links:
        collection = link.collection
        if not access.can_read(collection.library_id):
            continue
        if link.collection_id in held:
            steps.append(Step("collection", collection.name, "already"))
        elif not access.can_write(collection.library_id):
            steps.append(
                Step(
                    "collection",
                    collection.name,
                    "stays",
                    "you may not change this collection",
                )
            )
        elif not access.may_hold(collection.library_id, target):
            steps.append(
                Step(
                    "collection",
                    collection.name,
                    "stays",
                    "a group's collection takes only that group's papers",
                )
            )
        else:
            steps.append(
                Step(
                    "collection",
                    collection.name,
                    "move",
                    apply=lambda c=collection: target.collection_links.append(
                        CollectionItem(collection_id=c.id, added_by=access.user.id)
                    ),
                )
            )
    if db is not None:
        on_target = set(
            db.scalars(select(NoteItem.note_id).where(NoteItem.item_id == target.id))
        )
        for note in db.scalars(
            select(Note)
            .join(NoteItem, NoteItem.note_id == Note.id)
            .where(
                NoteItem.item_id == source.id,
                Note.deleted_at.is_(None),
                Note.library_id.in_(access.readable),
            )
            .order_by(Note.title)
        ):
            name = note.title or "Untitled note"
            steps.append(
                Step("note", name, "already" if note.id in on_target else "move")
            )
    return steps


def _move_notes_and_stars(db: Session, source: Item, target: Item) -> None:
    """Notes about the paper are about the one that stays (everyone's,
    whoever can see them), and everyone's star moves along."""
    db.flush()
    db.execute(
        update(NoteItem)
        .where(
            NoteItem.item_id == source.id,
            NoteItem.note_id.not_in(
                select(NoteItem.note_id).where(NoteItem.item_id == target.id)
            ),
        )
        .values(item_id=target.id)
        .execution_options(synchronize_session=False)
    )
    db.execute(delete(NoteItem).where(NoteItem.item_id == source.id))
    db.execute(
        insert(Favourite)
        .from_select(
            ["user_id", "item_id", "created_at"],
            select(Favourite.user_id, literal(target.id), Favourite.created_at).where(
                Favourite.item_id == source.id
            ),
        )
        .on_conflict_do_nothing()
    )
    db.execute(delete(Favourite).where(Favourite.item_id == source.id))
    db.expire(source, ["favourites"])
    db.expire(target, ["favourites"])


def merge_items(db: Session, access: Access, source: Item, target: Item) -> list[Step]:
    """Merge ``source`` into ``target`` as planned and put ``source`` in the
    trash; returns the plan carried out."""
    steps = plan_merge(access, source, target, db)
    for step in steps:
        if step.apply is not None:
            step.apply()
    _move_notes_and_stars(db, source, target)
    db.flush()
    library.refresh_item(target)
    library.trash(source, access.user.id)
    db.flush()
    return steps
