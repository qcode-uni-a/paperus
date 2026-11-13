"""What paperus does by itself (``paperus.automations``): for the whole
server (the administrator's settings, shown to everyone), and for each
library one is in (its owner's switches: a person's own, a group's
admins')."""

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from paperus import automations
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.jobs import queue_own_papers
from paperus.models import Library
from paperus.system import load_config

router = APIRouter(tags=["automations"])


class ServerAutomations(BaseModel):
    """What the server does by itself (Administration → Settings)."""

    find_published: bool
    """Published versions of preprints looked for."""
    find_errata: bool
    """Corrections (errata) to papers looked for."""
    find_references: bool
    """Papers' reference lists looked for."""
    find_authors: bool
    """Papers' authors looked up at OpenAlex (ORCID iDs)."""
    open_access: bool
    """Open-access copies fetched for papers without a file (where their
    library wants them)."""
    ocr: bool
    """Scanned pages read (OCR)."""


class LibraryAutomations(BaseModel):
    library_id: uuid.UUID
    own_papers: bool
    """Its people's papers added each day by their ORCID iDs (a person's
    own; a group's members')."""
    open_access: bool
    """Its papers without a file get an open-access copy (where the server
    fetches them)."""
    can_change: bool
    """The person may switch them (their own library; a group's admins)."""


class Automations(BaseModel):
    server: ServerAutomations
    libraries: list[LibraryAutomations]
    """One's own library first, then one's groups'."""


class AutomationsIn(BaseModel):
    own_papers: bool | None = None
    open_access: bool | None = None


def _can_change(access: Access, library: Library) -> bool:
    if library.user_id is not None:
        return library.id == access.own_library
    return access.site_admin or (
        library.group_id is not None and access.is_group_admin(library.group_id)
    )


def _out(library: Library, access: Access) -> LibraryAutomations:
    return LibraryAutomations(
        library_id=library.id,
        **automations.of(library),
        can_change=_can_change(access, library),
    )


@router.get("/api/automations")
def get_automations(request: Request, db: DB, access: CurrentAccess) -> Automations:
    config = load_config(db, request.app.state.settings)
    libraries = sorted(
        (db.get(Library, library_id) for library_id in access.readable),
        key=lambda library: library is None or library.id != access.own_library,
    )
    return Automations(
        server=ServerAutomations(
            find_published=config.find_published,
            find_errata=config.find_errata,
            find_references=config.find_references,
            find_authors=config.find_authors,
            open_access=config.open_access_auto,
            ocr=config.ocr,
        ),
        libraries=[_out(library, access) for library in libraries if library],
    )


@router.put("/api/libraries/{library_id}/automations")
def set_automations(
    library_id: uuid.UUID,
    body: AutomationsIn,
    request: Request,
    db: DB,
    access: CurrentAccess,
) -> LibraryAutomations:
    """Switch a library's automations (its person; a group's admins)."""
    library = db.get(Library, library_id)
    if library is None or library_id not in access.readable:
        raise HTTPException(404, "library not found")
    if not _can_change(access, library):
        raise HTTPException(403, "only the library's owner can change this")
    before = automations.of(library)
    changed = {
        key: value
        for key, value in body.model_dump(exclude_none=True).items()
        if key in before
    }
    library.automations = {**(library.automations or {}), **changed}
    db.commit()
    if changed.get("own_papers") and not before["own_papers"]:
        queue_own_papers(request.app.state.jobs, library.id)
    return _out(library, access)
