"""What paperus does by itself for a library's papers, as its owner
chooses (Settings → Automations): a person for their own library, a
group's admins for the group's. Each switch has a default; only changes
are kept (``libraries.automations``). Adding one's own papers is a
person's alone (kept with their own library), with where they go. What it
does for the whole server (errata, reference lists, authors, OCR, whether
published versions and open-access copies are looked for at all) is the
administrator's (``system.SystemConfig``)."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus.models import Library

SWITCHES: dict[str, bool] = {"published": True, "open_access": True}
"""Every library's: ``published``: its preprints' published versions are
looked for (and added to them, where the papers are); ``open_access``: its
papers without a file get an open-access copy (where the server fetches
them, ``open_access_auto``)."""
OWN_PAPERS = "own_papers"
OWN_PAPERS_TO = "own_papers_to"
"""A person's (their own library's): their papers by their ORCID iD, from
OpenAlex, added each day (``paperus.own_papers``; on by default), to the
owner they choose; unset: where their new papers go (Settings → New
papers)."""


def of(library: Library) -> dict[str, Any]:
    """The library's switches, defaults filled in; a person's own library's
    with ``own_papers`` and ``own_papers_to``."""
    chosen = library.automations or {}
    found: dict[str, Any] = {
        key: bool(chosen.get(key, default)) for key, default in SWITCHES.items()
    }
    if library.user_id is not None:
        found[OWN_PAPERS] = bool(chosen.get(OWN_PAPERS, True))
        target = chosen.get(OWN_PAPERS_TO)
        found[OWN_PAPERS_TO] = uuid.UUID(target) if target else None
    return found


def libraries_with(db: Session, key: str, on: bool = True) -> set[uuid.UUID]:
    """The libraries with this switch on (or off)."""
    return {
        library.id
        for library in db.scalars(select(Library))
        if of(library).get(key) is on
    }
