"""People who wrote papers: author records shared by the installation, and
each paper's authors linked to them (issue #35).

A paper's authors come from its details (``library.citation_csl``: the
shown version with the paper's edits). Each is linked to a person, best
evidence first:

1. the same ORCID iD, then the same OpenAlex author id (ids win over names:
   two ids never meet in one person);
2. else the same *full* name, folded (accents, case, hyphens and dots
   ignored: "Mónica Benito" is "monica benito"). Initials are another name
   ("M. Benito"); they are only suggested as the same person, never joined;
3. a name several people share (after a split) goes to the one with
   co-authors on this paper; otherwise it stays unlinked, "to check".

Links made by hand (``AuthorSource.HAND``) are kept by later passes; a split
remembers the two people as different (``AuthorsApart``).

Linking happens in the background (``paperus.jobs``): ``library.refresh_item``
stamps ``Item.authors_key`` when the names change, and ``link_waiting``
links the papers whose names are not linked yet.
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from paperus import library
from paperus.models import Author, AuthorsApart, Authorship, AuthorSource, Item

# Papers linked per round of ``link_waiting`` (committed after each).
BATCH = 200

_ORCID = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", re.IGNORECASE)


def fold(name: str) -> str:
    """A name for comparing: lower case, no accents, words only."""
    plain = "".join(
        c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)
    )
    return " ".join(re.sub(r"[^\w]+", " ", plain.casefold()).split())


@dataclass(frozen=True)
class Written:
    """An author as a paper's details give them."""

    written: str
    """"Family, Given" (or the literal name)."""
    shown: str
    """"Given Family"."""
    orcid: str | None = None

    @property
    def key(self) -> str:
        return fold(self.shown)


def orcid_of(value: object) -> str | None:
    """The iD in an ORCID value ("https://orcid.org/0000-…" or bare)."""
    match = _ORCID.search(str(value or ""))
    return match.group(1).upper() if match else None


def written_authors(csl: dict[str, Any]) -> list[Written]:
    """The authors in CSL-JSON, in order (entries without a name left out)."""
    found = []
    for person in csl.get("author") or []:
        if not isinstance(person, dict):
            continue
        family = str(person.get("family") or "").strip()
        given = str(person.get("given") or "").strip()
        literal = str(person.get("literal") or "").strip()
        orcid = orcid_of(person.get("ORCID"))
        if family:
            found.append(
                Written(
                    ", ".join(filter(None, [family, given])),
                    " ".join(filter(None, [given, family])),
                    orcid,
                )
            )
        elif literal:
            found.append(Written(literal, literal, orcid))
    return found


def _accents(name: str) -> int:
    return sum(1 for c in name if ord(c) > 127)


def _better_name(author: Author, shown: str) -> None:
    """Keep the fuller spelling of the same name (with its accents)."""
    if _accents(shown) > _accents(author.name):
        author.name = shown


def link(db: Session, item: Item) -> None:
    """Link the paper's authors to people (see the module's description);
    authors already linked under the same name at the same place keep their
    person. Does not commit."""
    csl = library.citation_csl(item)
    wanted = written_authors(csl)
    by_position = {a.position: a for a in item.authorships}
    for position, person in enumerate(wanted, start=1):
        old = by_position.pop(position, None)
        if old is not None and old.key == person.key:
            old.written = person.written
            if person.orcid and not old.orcid:
                old.orcid = person.orcid
            if old.author_id is None or (old.source == AuthorSource.NAME and old.orcid):
                _resolve(db, item, old)
            continue
        if old is not None:
            item.authorships.remove(old)
            db.flush()
        authorship = Authorship(
            item_id=item.id,
            position=position,
            written=person.written,
            key=person.key,
            orcid=person.orcid,
            source=AuthorSource.NAME,
        )
        item.authorships.append(authorship)
        db.flush()
        _resolve(db, item, authorship, shown=person.shown)
    for gone in by_position.values():
        item.authorships.remove(gone)
    # Names several people share, once the paper's other authors are known.
    for authorship in item.authorships:
        if authorship.author_id is None:
            _resolve(db, item, authorship)
    item.authors_key = library.authors_key(csl)
    item.authors_linked = item.authors_key
    db.flush()


def _resolve(
    db: Session, item: Item, authorship: Authorship, shown: str | None = None
) -> None:
    """Find (or make) the person for an authorship; by hand stays."""
    if authorship.source == AuthorSource.HAND:
        return
    shown = shown or _shown(authorship.written)
    for column, value, source in (
        (Author.orcid, authorship.orcid, AuthorSource.ORCID),
        (Author.openalex_id, authorship.openalex_id, AuthorSource.OPENALEX),
    ):
        if not value:
            continue
        author = db.scalar(select(Author).where(column == value))
        if author is None:
            # The person known by name, without an id of this kind yet.
            author = _one_by_name(db, item, authorship, without=column)
            if author is None:
                author = Author(name=shown, key=authorship.key)
                db.add(author)
            setattr(author, column.key, value)
            db.flush()
        _better_name(author, shown)
        authorship.author_id, authorship.source = author.id, source
        db.flush()
        return
    author = _one_by_name(db, item, authorship)
    if author is None:
        if _shared_name(db, authorship.key):
            authorship.author_id = None  # several people: to check
            return
        author = Author(name=shown, key=authorship.key)
        db.add(author)
        db.flush()
    _better_name(author, shown)
    authorship.author_id, authorship.source = author.id, AuthorSource.NAME


def _shown(written: str) -> str:
    family, _, given = written.partition(",")
    return " ".join(filter(None, [given.strip(), family.strip()]))


def _shared_name(db: Session, key: str) -> bool:
    return (db.scalar(select(func.count()).where(Author.key == key)) or 0) > 1


def _one_by_name(
    db: Session,
    item: Item,
    authorship: Authorship,
    without: Any = None,  # noqa: ANN401
) -> Author | None:
    """The person of this full name: the only one, or (several people of
    that name) the one who wrote with this paper's other authors."""
    query = select(Author).where(Author.key == authorship.key)
    if without is not None:
        query = query.where(without.is_(None))
    people = list(db.scalars(query))
    if len(people) <= 1:
        return people[0] if people else None
    others = [
        a.author_id
        for a in item.authorships
        if a.author_id is not None and a.position != authorship.position
    ]
    if not others:
        return None
    mine, theirs = aliased(Authorship), aliased(Authorship)
    shared = {
        author_id
        for author_id in db.scalars(
            select(mine.author_id)
            .join(theirs, theirs.item_id == mine.item_id)
            .where(
                mine.author_id.in_([p.id for p in people]),
                theirs.author_id.in_(others),
                mine.item_id != item.id,
            )
        )
    }
    return (
        next((p for p in people if p.id in shared), None) if len(shared) == 1 else None
    )


def waiting() -> Any:  # noqa: ANN401 (a condition)
    """Papers whose authors are not linked (yet, or since their names changed)."""
    return or_(
        Item.authors_linked.is_(None),
        Item.authors_key.is_distinct_from(Item.authors_linked),
    )


def link_waiting(db: Session, *, limit: int = 100_000) -> int:
    """Link the authors of papers waiting for it, a batch at a time
    (committed after each); people left without papers go. Returns how many
    papers were linked."""
    done = 0
    while done < limit:
        items = list(
            db.scalars(select(Item).where(waiting()).order_by(Item.id).limit(BATCH))
        )
        if not items:
            break
        for item in items:
            link(db, item)
        db.commit()
        done += len(items)
    db.execute(
        delete(Author).where(
            ~exists().where(Authorship.author_id == Author.id),
        )
    )
    db.commit()
    return done


# By hand: split, merge, assign.


class Refused(ValueError):
    pass


def apart(db: Session, one: uuid.UUID, other: uuid.UUID) -> None:
    """Remember two people as different."""
    first, second = sorted([one, other])
    if db.get(AuthorsApart, (first, second)) is None:
        db.add(AuthorsApart(first=first, second=second))


def are_apart(db: Session, one: uuid.UUID, other: uuid.UUID) -> bool:
    first, second = sorted([one, other])
    return db.get(AuthorsApart, (first, second)) is not None


def split(db: Session, author: Author, item_ids: list[uuid.UUID]) -> Author:
    """These papers are by someone else of the same name: a new person, who
    stays apart from this one. Commits."""
    moving = list(
        db.scalars(
            select(Authorship).where(
                Authorship.author_id == author.id, Authorship.item_id.in_(item_ids)
            )
        )
    )
    if not moving:
        raise Refused("none of these papers is by this person")
    other = Author(name=author.name, key=author.key)
    db.add(other)
    db.flush()
    for authorship in moving:
        authorship.author_id, authorship.source = other.id, AuthorSource.HAND
    # The ids of the papers that moved go with them.
    if author.orcid and all(a.orcid == author.orcid for a in moving):
        other.orcid, author.orcid = author.orcid, None
    apart(db, author.id, other.id)
    db.commit()
    return other


def merge(db: Session, keep: Author, other: Author) -> None:
    """The same person: ``other``'s papers go to ``keep``. Refused for two
    different ORCID or OpenAlex ids. Commits."""
    if keep.id == other.id:
        raise Refused("the same person already")
    for column in ("orcid", "openalex_id"):
        mine, theirs = getattr(keep, column), getattr(other, column)
        if mine and theirs and mine != theirs:
            raise Refused(f"they have different {column.replace('_id', '')} ids")
    for column in ("orcid", "openalex_id"):
        value = getattr(other, column)
        if value and not getattr(keep, column):
            setattr(other, column, None)
            db.flush()
            setattr(keep, column, value)
    _better_name(keep, other.name)
    for authorship in db.scalars(
        select(Authorship).where(Authorship.author_id == other.id)
    ):
        authorship.author_id = keep.id
        authorship.source = AuthorSource.HAND
    db.execute(
        delete(AuthorsApart).where(
            or_(
                and_(AuthorsApart.first == other.id),
                and_(AuthorsApart.second == other.id),
            )
        )
    )
    db.delete(other)
    db.commit()


def assign(db: Session, authorship: Authorship, author: Author | None) -> None:
    """A paper's author is this person (None: a new person of that name).
    Commits."""
    if author is None:
        author = Author(name=_shown(authorship.written), key=authorship.key)
        db.add(author)
        db.flush()
    authorship.author_id, authorship.source = author.id, AuthorSource.HAND
    db.commit()
