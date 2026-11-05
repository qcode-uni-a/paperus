"""Change numbers: which items changed since a client last looked.

Every transaction that changes an item (or its versions, identifiers, files,
tags and collection memberships), a tag or a collection takes the next number
from the library's counter and stamps it on what changed (like Zotero's
library version). Taking the number locks the counter row
until commit, so numbers become visible in order and ``since=N`` never misses
a change that commits late.
"""

from itertools import chain

from sqlalchemy import event, select, update
from sqlalchemy.orm import Session, UOWTransaction

from paperus.models import (
    ChangeCounter,
    Collection,
    CollectionItem,
    File,
    Identifier,
    Item,
    ItemLibrary,
    ItemTag,
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


def _stamped(obj: object) -> Item | Tag | Collection | None:
    """The object whose change number a change to ``obj`` moves."""
    match obj:
        case Item() | Tag() | Collection():
            return obj
        case Version() | ItemTag() | CollectionItem() | ItemLibrary():
            return obj.item
        case Identifier() | File():
            return obj.version.item if obj.version else None
    return None


@event.listens_for(Session, "before_flush")
def _stamp_changes(db: Session, flush: UOWTransaction, instances: object) -> None:
    changed = chain(
        db.new,
        (obj for obj in db.dirty if db.is_modified(obj, include_collections=True)),
        db.deleted,
    )
    stamped = {target for obj in changed if (target := _stamped(obj)) is not None}
    if not stamped:
        return
    with db.no_autoflush:
        if _INFO_KEY not in db.info:
            db.info[_INFO_KEY] = _next_change(db)
        for target in stamped:
            target.change = db.info[_INFO_KEY]


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def _forget_change(db: Session) -> None:
    db.info.pop(_INFO_KEY, None)
