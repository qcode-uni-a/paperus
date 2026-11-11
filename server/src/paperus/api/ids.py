"""IDs made on a device (offline, docs/apps.md, "Offline and sync"): a new
note, tag, collection or annotation may bring its own ID, a UUIDv7 as the
server makes them, so a device knows it before it is online, and a create
sent again (after a dropped connection) makes one record."""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import HTTPException
from pydantic import AfterValidator
from sqlalchemy.orm import Session


def _version_7(value: uuid.UUID | None) -> uuid.UUID | None:
    if value is not None and value.version != 7:
        raise ValueError("an ID made on a device is a UUIDv7")
    return value


NewId = Annotated[uuid.UUID | None, AfterValidator(_version_7)]
"""The new record's ID, if made on the device."""


def new_id(record_id: uuid.UUID | None) -> dict[str, uuid.UUID]:
    """The ID to make a record with, if given (else the database makes one)."""
    return {"id": record_id} if record_id is not None else {}


def sent_again[T](
    db: Session, model: type[T], record_id: uuid.UUID | None, sees: Callable[[T], bool]
) -> T | None:
    """What a create sent again made: the record with this ID if the person
    sees it (the answer is as for the first time); None for a new ID; 409 if
    something they do not see has it."""
    if record_id is None:
        return None
    found = db.get(model, record_id)
    if found is not None and not sees(found):
        raise HTTPException(409, "this ID is taken")
    return found
