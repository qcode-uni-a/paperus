"""What paperus does by itself for a library's papers, as its owner
chooses (Settings → Automations): a person for their own library, a
group's admins for the group's. Each switch has a default by the kind of
library; only changes are kept (``libraries.automations``). What it does
for the whole server (published versions, errata, reference lists,
authors, OCR, whether open-access copies are fetched at all) is the
administrator's (``system.SystemConfig``)."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus.models import Library

PERSONAL: dict[str, bool] = {"own_papers": True, "open_access": True}
"""A person's library: ``own_papers``: their papers (by their ORCID iD,
from OpenAlex) added each day (``paperus.own_papers``); ``open_access``:
papers in it without a file get an open-access copy, where the server
allows it (``open_access_auto``)."""
GROUP: dict[str, bool] = {"own_papers": False, "open_access": True}
"""A group's: ``own_papers``: its members' papers (by their ORCID iDs)
added each day: a group's list of its papers, if its admins want one."""


def defaults(library: Library) -> dict[str, bool]:
    return PERSONAL if library.user_id is not None else GROUP


def of(library: Library) -> dict[str, bool]:
    """The library's switches, defaults filled in."""
    chosen = library.automations or {}
    return {
        key: bool(chosen.get(key, default))
        for key, default in defaults(library).items()
    }


def libraries_with(db: Session, key: str, on: bool = True) -> set[uuid.UUID]:
    """The libraries with this switch on (or off)."""
    return {
        library.id for library in db.scalars(select(Library)) if of(library)[key] is on
    }
