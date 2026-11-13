"""One's own papers, added by themselves (Settings → Automations, "Add my
papers", a person's switch): each day, the works OpenAlex lists under a
person's ORCID iD that are in no library they can read (the trash
included) are added by DOI (its details from its registry), as "Add"
under Manage → Missing does, as added by them, to the owner they chose
(else where their new papers go: their own library, or a group they may
add papers to). A work is handled
once (``own_papers_seen`` of their own library): one removed stays
removed; one that is somewhere they can see is left there. The journal
version of a preprint there (renamed, so listed apart) becomes its
published version (``published``), not a paper of its own. A few dozen a
day each, so a long list comes over a few days. They are told under the
bell; a paper out in the last week is celebrated (``notifications``)."""

import logging
import uuid

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import (
    automations,
    library,
    metadata,
    notifications,
    published,
    works,
)
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
    """People's own libraries with the switch on (their ORCID iD set, not
    deactivated)."""
    on = automations.libraries_with(db, automations.OWN_PAPERS)
    return list(
        db.scalars(
            select(Library)
            .join(User, User.id == Library.user_id)
            .where(
                Library.id.in_(on),
                User.orcid.is_not(None),
                User.deactivated_at.is_(None),
            )
            .order_by(Library.id)
        )
    )


def target(db: Session, own: Library, user: User) -> uuid.UUID:
    """Where their papers go: the owner they chose, else where their new
    papers go; while they may add papers there, else their own library."""
    chosen = automations.of(own)[automations.OWN_PAPERS_TO] or user.default_library_id
    if chosen is None or chosen == own.id:
        return own.id
    if Access.of(db, user).role_in_library(chosen) in (None, Role.READER):
        return own.id
    return chosen


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
    # The journal version of a preprint here (renamed on publication, so
    # OpenAlex lists it apart): added to it, not as a paper of its own.
    if kind in published.JOURNAL and (
        preprint := published.preprint_of(
            db, Access.of(db, user).readable, metadata.csl_title(csl)
        )
    ):
        published.add_published(db, http, preprint, doi, "OpenAlex (ORCID iD)")
        db.commit()
        return None
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
    db: Session, http: httpx2.Client, own: Library, contact_email: str | None = None
) -> list[Item]:
    """Add the person's papers not yet where they can see them, to the
    owner they chose; commits; those added. Raises ``works.Unavailable``
    if OpenAlex (or a DOI's registry) does not answer: tried again
    tomorrow."""
    user = db.get(User, own.user_id) if own.user_id else None
    if user is None or not user.orcid:
        return []
    to = target(db, own, user)
    seen = set(own.own_papers_seen or [])
    added: list[Item] = []
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
                item = _add(db, http, to, user, work.doi)
                if item is not None:
                    added.append(item)
            seen.add(work.doi)
    finally:
        if added:
            notifications.own_added(db, user.id, db.get(Library, to) or own, added)
        own = db.get(Library, own.id) or own
        own.own_papers_seen = sorted(seen)
        db.commit()
    log.info("own papers of %s: %d added", user.id, len(added))
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
