"""Papers added by their authors' ORCID iDs (Settings → Automations, "Add
papers by ORCID iD"): each day, the works OpenAlex lists under the ORCID iD
of a library's person (a group's: of each member who may add papers) that
are in no library that person can read (the trash included) are added to
the library by DOI (its details from its registry), as "Add" under Manage
→ Missing does, as added by them. A work is handled once per library
(``libraries.own_papers_seen``): one removed stays removed. A few dozen a
day each, so a long list comes over a few days. The people are told under
the bell; a paper out in the last week is celebrated (``notifications``)."""

import logging
import uuid

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import automations, library, metadata, notifications, works
from paperus.access import Access
from paperus.identifiers import Scheme, implied_by_doi
from paperus.models import (
    Identifier,
    Item,
    Library,
    MetadataSource,
    Role,
    User,
    Version,
)

log = logging.getLogger(__name__)

PER_DAY = 30
"""Papers added to a library a day at most."""


def waiting(db: Session) -> list[Library]:
    """Libraries with the switch on."""
    on = automations.libraries_with(db, "own_papers")
    return list(db.scalars(select(Library).where(Library.id.in_(on))))


def people(db: Session, library: Library) -> list[User]:
    """Whose papers go into the library: its person, or the group's members
    who may add papers to it; with an ORCID iD, not deactivated."""
    ids = (
        [library.user_id]
        if library.user_id is not None
        else notifications.people_of(db, library.id)
    )
    found = list(
        db.scalars(
            select(User).where(
                User.id.in_(ids), User.orcid.is_not(None), User.deactivated_at.is_(None)
            )
        )
    )
    if library.user_id is not None:
        return found
    return [
        user
        for user in found
        if Access.of(db, user).role_in_library(library.id) not in (None, Role.READER)
    ]


def _add(
    db: Session, http: httpx2.Client, library_id: uuid.UUID, user: User, doi: str
) -> Item | None:
    """The paper of this DOI, new in the library (its details looked up);
    None if its registry does not know it or it is there already."""
    try:
        csl, kind = metadata.lookup_doi(http, doi)
    except metadata.DOINotFound:
        log.info("own paper %s: not found at its registry", doi)
        return None
    except metadata.MetadataUnavailable as error:
        raise works.Unavailable(str(error)) from error
    try:
        with db.begin_nested():
            item = library.create_item(
                db,
                library_id,
                kind=kind,
                label=None,
                csl=csl,
                source=MetadataSource.LOOKUP,
                identifiers=[(Scheme.DOI, doi), *implied_by_doi(doi)],
                added_by=user.id,
            )
    except library.IdentifierTaken:
        return None
    db.commit()
    return item


def add_new(
    db: Session, http: httpx2.Client, owner: Library, contact_email: str | None = None
) -> list[Item]:
    """Add the papers of the library's people not yet there; commits; those
    added. A person OpenAlex (or the DOIs' registry) does not answer for is
    tried again tomorrow."""
    seen = set(owner.own_papers_seen or [])
    added: list[Item] = []
    for user in people(db, owner):
        mine: list[Item] = []
        try:
            found = works.works_of(
                http, orcid=user.orcid, openalex_id=None, contact_email=contact_email
            )
            known = _known(db, Access.of(db, user), found)
            for work in found:
                if work.doi in seen:
                    continue
                if not known & {work.doi, *work.copies}:
                    if len(added) >= PER_DAY:
                        break  # tomorrow
                    item = _add(db, http, owner.id, user, work.doi)
                    if item is not None:
                        added.append(item)
                        mine.append(item)
                seen.add(work.doi)
        except works.Unavailable as error:
            log.info("own papers of %s: %s", user.id, error)
        if mine:
            notifications.own_added(db, user.id, owner, mine)
    owner = db.get(Library, owner.id) or owner
    owner.own_papers_seen = sorted(seen)
    db.commit()
    log.info("own papers of library %s: %d added", owner.id, len(added))
    return added


def _known(db: Session, access: Access, found: list[works.Work]) -> set[str]:
    """The works' DOIs in a library the person can read (the trash too)."""
    return set(
        db.scalars(
            select(Identifier.value)
            .join(Version, Version.id == Identifier.version_id)
            .join(Item, Item.id == Version.item_id)
            .where(
                Identifier.scheme == Scheme.DOI,
                Identifier.value.in_([d for w in found for d in [w.doi, *w.copies]]),
                Item.library_id.in_(access.readable),
            )
        )
    )
