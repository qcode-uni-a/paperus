"""Change numbers: which items changed since a client last looked.

Every transaction that changes an item (or its versions, identifiers, files,
tags and collection memberships), a tag, a collection, a note, an annotation
or where someone is reading (``ItemView``) takes the next number
from the library's counter and stamps it on what changed (like Zotero's
library version). Taking the number locks the counter row
until commit, so numbers become visible in order and ``since=N`` never misses
a change that commits late.
"""

from datetime import UTC, datetime
from itertools import chain

from sqlalchemy import event, select, update
from sqlalchemy.orm import Session, UOWTransaction

from paperus.models import (
    Annotation,
    ChangeCounter,
    Collection,
    CollectionItem,
    CollectionNote,
    File,
    Identifier,
    Item,
    ItemTag,
    ItemView,
    Note,
    NoteItem,
    Tag,
    Version,
)

COUNTER = "library"
_INFO_KEY = "paperus_change"


def current_change(db: Session) -> int:
    return db.scalars(
        select(ChangeCounter.value).where(ChangeCounter.name == COUNTER)
    ).one()


def _next_change(db: Session) -> int:
    # On the connection, so it does not trigger another flush.
    return (
        db.connection()
        .scalars(
            update(ChangeCounter)
            .where(ChangeCounter.name == COUNTER)
            .values(value=ChangeCounter.value + 1)
            .returning(ChangeCounter.value)
        )
        .one()
    )


def change_number(db: Session) -> int:
    """This transaction's change number, taken at its first change (for
    statements that bypass the ORM's flush, such as upserts)."""
    if _INFO_KEY not in db.info:
        db.info[_INFO_KEY] = _next_change(db)
    return db.info[_INFO_KEY]


Stamped = Item | Tag | Collection | Note | Annotation | ItemView


def _stamped(obj: object) -> Stamped | None:
    """The object whose change number a change to ``obj`` moves."""
    match obj:
        case Item() | Tag() | Collection() | Note() | Annotation() | ItemView():
            return obj
        case NoteItem() | CollectionNote():
            return obj.note
        case Version() | ItemTag() | CollectionItem():
            return obj.item
        case Identifier() | File():
            return obj.version.item if obj.version else None
    return None


@event.listens_for(Session, "before_flush")
def _stamp_changes(db: Session, flush: UOWTransaction, instances: object) -> None:
    changed_objects = list(
        chain(
            db.new,
            (obj for obj in db.dirty if db.is_modified(obj, include_collections=True)),
            db.deleted,
        )
    )
    stamped = {
        target for obj in changed_objects if (target := _stamped(obj)) is not None
    }
    if not stamped:
        return
    # A note filed in a collection or linked to a paper is not "changed" for
    # lists (it would move up for everyone, e.g. when a reader files a group
    # note privately); only its own fields count.
    # Checked before the change number is set (that would count too).
    own_change = {
        id(target)
        for target in stamped
        if target in db.new or db.is_modified(target, include_collections=False)
    }
    # Likewise a paper tagged or filed (perhaps privately, by a reader of a
    # group paper): its versions, files and identifiers are the paper's own.
    content = {
        id(target)
        for obj in changed_objects
        if isinstance(obj, Version | Identifier | File)
        and (target := _stamped(obj)) is not None
    }
    with db.no_autoflush:
        number = change_number(db)
        now = datetime.now(UTC)
        for target in stamped:
            target.change = number
            if isinstance(target, Item | Note) and id(target) in own_change | content:
                target.changed_at = now


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def _forget_change(db: Session) -> None:
    db.info.pop(_INFO_KEY, None)
