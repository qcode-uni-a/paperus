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

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx2
from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from paperus import abstracts, library
from paperus.identifiers import Scheme, is_arxiv_doi
from paperus.importing.references import Pacer
from paperus.models import (
    Author,
    AuthorChange,
    AuthorChangeKind,
    AuthorsApart,
    Authorship,
    AuthorSource,
    Identifier,
    Item,
    Version,
)

log = logging.getLogger(__name__)

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


def valid_orcid(orcid: str) -> bool:
    """Whether an iD's check digit fits (ISO 7064 MOD 11-2)."""
    digits = orcid.replace("-", "")
    total = 0
    for digit in digits[:-1]:
        total = (total + int(digit)) * 2
    check = (12 - total % 11) % 11
    return digits[-1] == ("X" if check == 10 else str(check))


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


def _better_name(author: Author, written: str) -> None:
    """Keep the fuller spelling: with its accents, else the longer one of
    the same family name and fitting given names ("Michel Pioro-Ladrière",
    not "M. Pioro-Ladrière"; never "Qian Dong" for "Shi-Hai Dong", whom an
    id may have joined by mistake). ``written``: "Family, Given"."""
    shown = _shown(written)
    if _accents(shown) > _accents(author.name):
        author.name = shown
        return
    family, _, given = written.partition(",")
    mine, _, my_given = (author.written or "").partition(",")
    if (
        len(shown) > len(author.name)
        and fold(family) == fold(mine)
        and _given_fits(given, my_given)
    ):
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
        _take_ids(db, author, authorship)
        _better_name(author, authorship.written)
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
    _better_name(author, authorship.written)
    authorship.author_id, authorship.source = author.id, AuthorSource.NAME


def _take_ids(db: Session, author: Author, authorship: Authorship) -> None:
    """The person takes the paper's other ids they lack (unless someone
    else has them), so a paper with another id is someone else."""
    for column, value in (
        (Author.orcid, authorship.orcid),
        (Author.openalex_id, authorship.openalex_id),
    ):
        if value and getattr(author, column.key) is None:
            taken = db.scalar(select(Author.id).where(column == value))
            if taken is None:
                setattr(author, column.key, value)
    db.flush()


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


# OpenAlex: who the authors are (ids, ORCID iDs) and where they were.

OPENALEX = "https://api.openalex.org/works"
OPENALEX_BATCH = 50
_PACER = Pacer(0.2)
# Papers looked up per round of ``check_waiting`` (an hourly job).
LOOKUPS = 1000


def _doi(item: Item) -> str | None:
    """The DOI OpenAlex knows the paper by: a journal's (OpenAlex files a
    preprint under its journal version's DOI once it knows both), the shown
    version's first; else arXiv's."""
    shown = library.preferred_version(item)
    versions = [shown] if shown else []
    versions += [v for v in item.versions if v is not shown]
    found = [
        (identifier.scheme, identifier.value.lower())
        for version in versions
        for identifier in version.identifiers
    ]
    for scheme, value in found:
        if scheme == Scheme.DOI and not is_arxiv_doi(value):
            return value
    for scheme, value in found:
        if scheme == Scheme.DOI:
            return value
        if scheme == Scheme.ARXIV:
            return f"10.48550/arxiv.{value}"
    return None


def look_up(
    db: Session,
    http: httpx2.Client,
    items: list[Item],
    *,
    contact_email: str | None = None,
    pacer: Pacer = _PACER,
) -> int:
    """Each paper's authors as OpenAlex knows the paper (by its DOI, 50 to
    a request): their OpenAlex ids, ORCID iDs and affiliations on it; then
    linked again (ids win over names). Its abstract too, if its details
    have none (``paperus.abstracts``). Returns how many papers OpenAlex
    knew. Does not commit."""
    now = datetime.now(UTC)
    by_doi: dict[str, list[Item]] = {}
    for item in items:
        item.authors_checked_at = now
        if (doi := _doi(item)) is not None:
            by_doi.setdefault(doi, []).append(item)
    known = 0
    dois = list(by_doi)
    for start in range(0, len(dois), OPENALEX_BATCH):
        params = {
            "filter": "doi:" + "|".join(dois[start : start + OPENALEX_BATCH]),
            "per-page": str(OPENALEX_BATCH),
            "select": "doi,authorships,abstract_inverted_index",
        }
        if contact_email:
            params["mailto"] = contact_email
        pacer()
        try:
            response = http.get(OPENALEX, params=params, timeout=20)
            response.raise_for_status()
            works = response.json().get("results") or []
        except (httpx2.HTTPError, ValueError) as error:
            log.info("no authors from OpenAlex: %s", error)
            continue
        for work in works:
            doi = str(work.get("doi") or "").removeprefix("https://doi.org/").lower()
            for item in by_doi.get(doi, []):
                _take(db, item, work.get("authorships") or [])
                found = abstracts.from_openalex(work.get("abstract_inverted_index"))
                abstracts.take(item, found, replace=True)
                known += 1
    db.flush()
    return known


def _take(db: Session, item: Item, theirs: list[Any]) -> None:
    entries = [e for e in theirs if isinstance(e, dict)]
    for authorship in item.authorships:
        entry = _match(authorship, entries)
        if entry is None:
            continue
        person = entry.get("author") or {}
        openalex = str(person.get("id") or "").rsplit("/", 1)[-1]
        if re.fullmatch(r"A\d+", openalex):
            authorship.openalex_id = openalex
        authorship.orcid = authorship.orcid or orcid_of(person.get("orcid"))
        if not authorship.affiliation:
            places = [
                str(place.get("display_name"))
                for place in entry.get("institutions") or []
                if isinstance(place, dict) and place.get("display_name")
            ]
            raw = [str(r) for r in entry.get("raw_affiliation_strings") or [] if r]
            found = "; ".join(dict.fromkeys(places)) or (raw[0] if raw else "")
            authorship.affiliation = found[:500] or None
        _resolve(db, item, authorship)


def _match(
    authorship: Authorship, entries: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """OpenAlex's entry for this author: at the same place if the family
    name fits, else the only one it fits."""
    family = fold(authorship.written.partition(",")[0]).split()

    def fits(entry: dict[str, Any]) -> bool:
        shown = fold(str((entry.get("author") or {}).get("display_name") or ""))
        return bool(family) and all(word in shown.split() for word in family)

    position = authorship.position - 1
    if position < len(entries) and fits(entries[position]):
        return entries[position]
    fitting = [e for e in entries if fits(e)]
    return fitting[0] if len(fitting) == 1 else None


def check_waiting(
    db: Session,
    http: httpx2.Client,
    *,
    contact_email: str | None = None,
    limit: int = LOOKUPS,
) -> int:
    """Look up the authors of papers never looked up (with a DOI or arXiv
    ID, linked already), and again those that got a journal's DOI since
    (a preprint's published version, found later), up to ``limit``,
    committing after each request's worth. Returns how many papers OpenAlex
    knew."""
    has_id = (
        select(Identifier.id)
        .join(Version, Version.id == Identifier.version_id)
        .where(
            Version.item_id == Item.id,
            Identifier.scheme.in_([Scheme.DOI, Scheme.ARXIV]),
        )
        .exists()
    )
    new_doi = (
        select(Identifier.id)
        .join(Version, Version.id == Identifier.version_id)
        .where(
            Version.item_id == Item.id,
            Identifier.scheme == Scheme.DOI,
            Identifier.value.not_like("10.48550/%"),
            Identifier.created_at > Item.authors_checked_at,
        )
        .exists()
    )
    items = list(
        db.scalars(
            select(Item)
            .where(
                or_(Item.authors_checked_at.is_(None), new_doi),
                Item.authors_linked.is_not(None),
                has_id,
            )
            .order_by(Item.authors_checked_at.asc().nulls_first(), Item.id)
            .limit(limit)
        )
    )
    known = 0
    for start in range(0, len(items), OPENALEX_BATCH):
        known += look_up(
            db, http, items[start : start + OPENALEX_BATCH], contact_email=contact_email
        )
        db.commit()
    return known


# Probably the same person: suggestions, decided by a person.

# Authors of one family name compared pairwise, at most this many.
MAX_NAMESAKES = 60


@dataclass
class Likely:
    """Two people who are probably one."""

    one: uuid.UUID
    other: uuid.UUID
    shared: int
    """Co-authors in common."""


def _given_fits(one: str, other: str) -> bool:
    """Given names that may be the same person's: "M." and "Mónica", "M. F."
    and "Mario Fernando"; not "Mónica" and "María"."""
    a, b = fold(one).split(), fold(other).split()
    if not a or not b:
        return False
    for x, y in zip(a, b, strict=False):
        if x[0] != y[0] or (len(x) > 1 and len(y) > 1 and x != y):
            return False
    return True


def _full_given(given: str) -> bool:
    """A given name written out ("Mónica"), not an initial ("M.")."""
    words = fold(given).split()
    return bool(words) and len(words[0]) > 1


def likely_the_same(
    db: Session, visible: list[Any], *, limit: int | None = 50
) -> list[Likely]:
    """Pairs of people, among the authors of the papers ``visible`` finds,
    with the same family name and given names that fit, not said to be
    different, never on one paper together and without two ORCID iDs; most
    co-authors in common first."""
    rows = db.execute(
        select(Authorship.author_id, Authorship.written, Authorship.item_id)
        .join(Item, Item.id == Authorship.item_id)
        .where(Authorship.author_id.is_not(None), *visible)
    )
    names: dict[uuid.UUID, set[tuple[str, str]]] = {}
    on_item: dict[uuid.UUID, set[uuid.UUID]] = {}
    for author_id, written, item_id in rows:
        if author_id is None:  # left out by the query; for the type checker
            continue
        family, _, given = written.partition(",")
        names.setdefault(author_id, set()).add((fold(family), given.strip()))
        on_item.setdefault(item_id, set()).add(author_id)
    # A person known by a full given name is that name, not their initials
    # ("Guido", also written "G.", is not "Gerda").
    for person, spellings in names.items():
        full = {(f, g) for f, g in spellings if _full_given(g)}
        if full:
            names[person] = full
    with_others: dict[uuid.UUID, set[uuid.UUID]] = {}
    for people in on_item.values():
        for person in people:
            with_others.setdefault(person, set()).update(people - {person})
    by_family: dict[str, set[uuid.UUID]] = {}
    for person, spellings in names.items():
        for family, _ in spellings:
            if family:
                by_family.setdefault(family, set()).add(person)
    orcids = dict(
        db.execute(
            select(Author.id, Author.orcid).where(
                Author.id.in_(list(names)), Author.orcid.is_not(None)
            )
        ).all()
    )
    kept_apart = {
        (row.first, row.second)
        for row in db.scalars(
            select(AuthorsApart).where(AuthorsApart.first.in_(list(names)))
        )
    }
    found: dict[tuple[uuid.UUID, uuid.UUID], Likely] = {}
    for family, people in by_family.items():
        if len(people) < 2 or len(people) > MAX_NAMESAKES:
            continue
        ordered = sorted(people)
        for i, one in enumerate(ordered):
            for other in ordered[i + 1 :]:
                if (one, other) in kept_apart or (one, other) in found:
                    continue
                if one in orcids and other in orcids and orcids[one] != orcids[other]:
                    continue
                # On one paper's author list together: two people (two
                # namesakes among a collaboration's thousands of authors share
                # all of them as co-authors).
                if other in with_others.get(one, set()):
                    continue
                if not any(
                    _given_fits(g1, g2)
                    for f1, g1 in names[one]
                    for f2, g2 in names[other]
                    if f1 == f2 == family
                ):
                    continue
                shared = len(
                    with_others.get(one, set()) & with_others.get(other, set())
                )
                found[(one, other)] = Likely(one, other, shared)
    return sorted(found.values(), key=lambda pair: -pair.shared)[:limit]


# By hand: split, merge, assign.


class Refused(ValueError):
    pass


def apart(db: Session, one: uuid.UUID, other: uuid.UUID) -> None:
    """Remember two people as different."""
    first, second = sorted([one, other])
    if db.get(AuthorsApart, (first, second)) is None:
        db.add(AuthorsApart(first=first, second=second))


def keep_apart(
    db: Session, one: Author, other: Author, *, by: uuid.UUID | None = None
) -> None:
    """Two people, not one, said by hand (logged). Commits."""
    apart(db, one.id, other.id)
    _log(db, AuthorChangeKind.APART, by, one, other, [])
    db.commit()


def are_apart(db: Session, one: uuid.UUID, other: uuid.UUID) -> bool:
    first, second = sorted([one, other])
    return db.get(AuthorsApart, (first, second)) is not None


def split(
    db: Session,
    author: Author,
    item_ids: list[uuid.UUID],
    *,
    by: uuid.UUID | None = None,
) -> Author:
    """These papers are by someone else of the same name: a new person, who
    stays apart from this one (logged as done ``by`` someone). Commits."""
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
    _log(db, AuthorChangeKind.SPLIT, by, author, other, moving)
    db.commit()
    return other


def _log(
    db: Session,
    kind: AuthorChangeKind,
    by: uuid.UUID | None,
    author: Author,
    other: Author,
    moved: list[Authorship],
) -> AuthorChange:
    change = AuthorChange(
        kind=kind,
        user_id=by,
        author_id=author.id,
        other_id=other.id,
        other_name=other.name,
        moved=[[str(a.item_id), a.position] for a in moved],
    )
    db.add(change)
    return change


def merge(
    db: Session,
    keep: Author,
    other: Author,
    *,
    by: uuid.UUID | None = None,
    logged: bool = True,
) -> None:
    """The same person: ``other``'s papers go to ``keep`` (logged as done
    ``by`` someone). Refused for two different ORCID iDs. Commits."""
    if keep.id == other.id:
        raise Refused("the same person already")
    # Two ORCID iDs are two people; OpenAlex has duplicate profiles, so
    # two OpenAlex ids may be one (the kept person keeps theirs).
    if keep.orcid and other.orcid and keep.orcid != other.orcid:
        raise Refused("they have different ORCID iDs")
    for column in ("orcid", "openalex_id"):
        value = getattr(other, column)
        if value and not getattr(keep, column):
            setattr(other, column, None)
            db.flush()
            setattr(keep, column, value)
    moved = list(db.scalars(select(Authorship).where(Authorship.author_id == other.id)))
    before = keep.name
    _better_name(keep, other.written or other.name)
    if logged:
        change = _log(db, AuthorChangeKind.MERGE, by, keep, other, moved)
        change.renamed_from = before if keep.name != before else None
    for authorship in moved:
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


def undo(db: Session, change: AuthorChange) -> None:
    """Take back a fix by hand. A merge: the papers that came from the other
    person go to a new person of that name, apart from this one (ids
    OpenAlex or ORCID gave stay here). A split: the two are one again. Kept
    apart: they may be suggested as one again. Refused when it can no
    longer be undone (undone already; one of them gone since). Commits."""
    if change.undone_at is not None:
        raise Refused("undone already")
    author = db.get(Author, change.author_id)
    if author is None:
        raise Refused("this person is no longer there")
    if change.kind == AuthorChangeKind.MERGE:
        moved = [
            authorship
            for item_id, position in change.moved
            if (authorship := db.get(Authorship, (uuid.UUID(item_id), position)))
            is not None
            and authorship.author_id == author.id
        ]
        if not moved:
            raise Refused("none of those papers is by this person now")
        other = Author(name=change.other_name, key=moved[0].key)
        db.add(other)
        db.flush()
        for authorship in moved:
            authorship.author_id = other.id
        apart(db, author.id, other.id)
        if change.renamed_from:
            author.name = change.renamed_from
    else:
        other = db.get(Author, change.other_id)
        if other is None:
            raise Refused("the other person is no longer there")
        first, second = sorted([author.id, other.id])
        db.execute(
            delete(AuthorsApart).where(
                AuthorsApart.first == first, AuthorsApart.second == second
            )
        )
        if change.kind == AuthorChangeKind.SPLIT:
            change.undone_at = datetime.now(UTC)
            merge(db, author, other, logged=False)  # commits
            return
    change.undone_at = datetime.now(UTC)
    db.commit()
