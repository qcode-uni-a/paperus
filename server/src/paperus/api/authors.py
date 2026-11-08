"""Authors as people (``paperus.authors``): who they are, their papers the
person may see, their co-authors and where they were; and the fixes by
hand: split, merge, and which person a paper's author is.

Author records are shared by the installation, but a person learns of an
author only through papers they may see: an author without such papers
does not exist for them.
"""

import uuid
from collections import Counter
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from paperus import authors
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.api.items import ItemOut, get_readable_item, item_out
from paperus.models import (
    Author,
    AuthorChange,
    AuthorChangeKind,
    Authorship,
    Item,
)

router = APIRouter(tags=["authors"])


class AuthorRow(BaseModel):
    id: uuid.UUID
    name: str
    """"Mónica Benito"."""
    written: str
    """The same, as on their papers: "Benito, Mónica" ("Family, Given")."""
    papers: int
    """Of the papers the person may see."""
    orcid: str | None = None


class Affiliation(BaseModel):
    name: str
    first_year: int | None
    last_year: int | None
    papers: int


class AuthorOut(AuthorRow):
    openalex_id: str | None = None
    spellings: list[str]
    """The names on their papers ("Benito, M.", "Benito, Mónica")."""
    coauthors: list[AuthorRow]
    """The most frequent first (on the papers the person may see)."""
    affiliations: list[Affiliation]
    """Where they were, from their papers; the newest first ("latest known")."""
    namesakes: list[AuthorRow]
    """Other people of the same name."""
    may_change: bool
    """Whether the person may split, merge or keep apart this author: one of
    their papers is the person's to change (author records are shared)."""
    changes: list["AuthorChangeOut"]
    """Fixes by hand, the newest first."""


class AuthorChangeOut(BaseModel):
    id: uuid.UUID
    kind: AuthorChangeKind
    at: datetime
    by_you: bool
    """Who else made it is not said (it would tell what papers they have)."""
    other_name: str | None
    """None: someone one sees no paper of."""
    other_id: uuid.UUID | None
    """The other person, if they are still there and seen."""
    papers: int
    """Of the papers whose author changed person, those one may see."""
    renamed_from: str | None = None
    """A merge that changed this person's name: the name before."""
    undone: bool
    may_undo: bool


def visible_papers(access: Access) -> list[ColumnElement[bool]]:
    """Papers whose authors the person sees: readable, not in the trash or
    the archive."""
    return [
        Item.deleted_at.is_(None),
        Item.archived_at.is_(None),
        access.item_filter(),
    ]


def _counts(
    db: Session, access: Access, author_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Authorship.author_id, func.count(func.distinct(Authorship.item_id)))
        .join(Item, Item.id == Authorship.item_id)
        .where(Authorship.author_id.in_(author_ids), *visible_papers(access))
        .group_by(Authorship.author_id)
    )
    return {author_id: count for author_id, count in rows if author_id is not None}


def _row(author: Author, papers: int) -> AuthorRow:
    return AuthorRow(
        id=author.id,
        name=author.name,
        written=author.written or author.name,
        papers=papers,
        orcid=author.orcid,
    )


def changeable_papers(access: Access) -> list[ColumnElement[bool]]:
    """Papers whose authors the person may fix: their own to change, not in
    the trash or the archive."""
    return [
        Item.deleted_at.is_(None),
        Item.archived_at.is_(None),
        access.item_filter(access.writable),
    ]


def may_change(db: Session, access: Access, author_id: uuid.UUID) -> bool:
    """Whether the person may fix this author by hand: a paper of theirs is
    the person's to change."""
    return bool(
        db.scalar(
            select(
                exists().where(
                    Authorship.author_id == author_id,
                    Authorship.item_id == Item.id,
                    Item.deleted_at.is_(None),
                    access.item_filter(access.writable),
                )
            )
        )
    )


def _changeable(db: Session, access: Access, *people: Author) -> None:
    for person in people:
        if not may_change(db, access, person.id):
            raise HTTPException(
                403, f"none of {person.name}'s papers is yours to change"
            )


def _changes(db: Session, access: Access, author: Author) -> list[AuthorChangeOut]:
    changes = list(
        db.scalars(
            select(AuthorChange)
            .where(
                or_(
                    AuthorChange.author_id == author.id,
                    AuthorChange.other_id == author.id,
                )
            )
            .order_by(AuthorChange.id.desc())
            .limit(20)
        )
    )
    moved = {uuid.UUID(i) for c in changes for i, _ in c.moved}
    seen = set(
        db.scalars(select(Item.id).where(Item.id.in_(moved), *visible_papers(access)))
    )
    others = {c.other_id for c in changes} | {c.author_id for c in changes}
    counts = _counts(db, access, list(others))
    mine = may_change(db, access, author.id)
    result = []
    for c in changes:
        other = next(
            (i for i in (c.other_id, c.author_id) if i != author.id and i in counts),
            None,
        )
        papers = sum(uuid.UUID(i) in seen for i, _ in c.moved)
        result.append(
            AuthorChangeOut(
                id=c.id,
                kind=AuthorChangeKind(c.kind),
                at=c.created_at,
                by_you=c.user_id == access.user.id,
                other_name=c.other_name if other or papers else None,
                renamed_from=c.renamed_from,
                other_id=other,
                papers=papers,
                undone=c.undone_at is not None,
                may_undo=c.undone_at is None and c.author_id == author.id and mine,
            )
        )
    return result


def visible_author(db: Session, access: Access, author_id: uuid.UUID) -> Author:
    """The author, if the person sees a paper of theirs (else 404)."""
    author = db.get(Author, author_id)
    if author is None or not _counts(db, access, [author.id]):
        raise HTTPException(404, "no such author")
    return author


@router.get("/api/authors")
def list_authors(
    response: Response,
    db: DB,
    access: CurrentAccess,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Literal["papers", "name"] = "papers",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuthorRow]:
    """The authors of the papers the person sees, with how many of those
    papers each wrote; ``q``: words of the name (accents and case ignored).
    ``X-Total-Count``: how many match."""
    papers = func.count(func.distinct(Authorship.item_id)).label("papers")
    query = (
        select(Author, papers)
        .join(Authorship, Authorship.author_id == Author.id)
        .join(Item, Item.id == Authorship.item_id)
        .where(*visible_papers(access))
        .group_by(Author.id)
    )
    # Any spelling on their papers: "michel" finds "M. Pioro-Ladrière" too.
    spelled = aliased(Authorship)
    for word in authors.fold(q or "").split():
        query = query.where(
            or_(
                Author.key.contains(word, autoescape=True),
                select(spelled.item_id)
                .where(
                    spelled.author_id == Author.id,
                    spelled.key.contains(word, autoescape=True),
                )
                .exists(),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    response.headers["X-Total-Count"] = str(total)
    # By name: as the person reads names, family names first or not.
    by_name = (
        func.lower(Author.written)
        if access.user.name_format == "family-given"
        else Author.key
    )
    order = [papers.desc(), by_name] if sort == "papers" else [by_name, papers.desc()]
    rows = db.execute(query.order_by(*order, Author.id).offset(offset).limit(limit))
    return [_row(author, count) for author, count in rows]


@router.get("/api/authors/{author_id}")
def get_author(author_id: uuid.UUID, db: DB, access: CurrentAccess) -> AuthorOut:
    """An author: names, ids, co-authors, where they were, and others of
    the same name (their papers: ``GET /api/items?author_id=``)."""
    author = visible_author(db, access, author_id)
    mine = list(
        db.execute(
            select(Authorship, Item.year)
            .join(Item, Item.id == Authorship.item_id)
            .where(Authorship.author_id == author.id, *visible_papers(access))
        )
    )
    item_ids = {a.item_id for a, _ in mine}
    spellings = Counter(a.written for a, _ in mine)
    other = aliased(Authorship)
    together = Counter(
        db.scalars(
            select(other.author_id)
            .join(Item, Item.id == other.item_id)
            .where(
                other.item_id.in_(item_ids),
                other.author_id.is_not(None),
                other.author_id != author.id,
                *visible_papers(access),
            )
        )
    )
    coauthor_ids = [author_id for author_id, _ in together.most_common(12) if author_id]
    named = {
        a.id: a for a in db.scalars(select(Author).where(Author.id.in_(coauthor_ids)))
    }
    places: dict[str, list[int | None]] = {}
    for authorship, year in mine:
        if authorship.affiliation:
            places.setdefault(authorship.affiliation, []).append(year)
    affiliations = [
        Affiliation(
            name=name,
            first_year=min((y for y in years if y), default=None),
            last_year=max((y for y in years if y), default=None),
            papers=len(years),
        )
        for name, years in places.items()
    ]
    affiliations.sort(key=lambda a: a.last_year or 0, reverse=True)
    namesakes = [
        a
        for a in db.scalars(
            select(Author).where(Author.key == author.key, Author.id != author.id)
        )
    ]
    counts = _counts(db, access, [a.id for a in namesakes])
    return AuthorOut(
        id=author.id,
        name=author.name,
        written=author.written or author.name,
        papers=len(item_ids),
        orcid=author.orcid,
        openalex_id=author.openalex_id,
        spellings=[name for name, _ in spellings.most_common()],
        coauthors=[_row(named[i], together[i]) for i in coauthor_ids if i in named],
        affiliations=affiliations,
        namesakes=[_row(a, counts[a.id]) for a in namesakes if a.id in counts],
        may_change=may_change(db, access, author.id),
        changes=_changes(db, access, author),
    )


class AuthorToCheck(BaseModel):
    item: ItemOut
    position: int
    written: str
    candidates: list[AuthorRow]
    """The people of that name."""


@router.get("/api/authors-to-check")
def authors_to_check(
    db: DB,
    access: CurrentAccess,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuthorToCheck]:
    """Authors of the papers the person may change not linked to anyone: a
    name several people share, with nothing to tell which one."""
    rows = list(
        db.execute(
            select(Authorship, Item)
            .join(Item, Item.id == Authorship.item_id)
            .where(Authorship.author_id.is_(None), *changeable_papers(access))
            .order_by(Item.id.desc(), Authorship.position)
            .limit(limit)
        )
    )
    keys = {a.key for a, _ in rows}
    people = list(db.scalars(select(Author).where(Author.key.in_(keys))))
    counts = _counts(db, access, [p.id for p in people])
    return [
        AuthorToCheck(
            item=item_out(item, access),
            position=authorship.position,
            written=authorship.written,
            # Only those one sees (others' namesakes stay theirs).
            candidates=[
                _row(p, counts[p.id])
                for p in people
                if p.key == authorship.key and counts.get(p.id)
            ],
        )
        for authorship, item in rows
    ]


class Split(BaseModel):
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    """Papers of this author that are by someone else of the same name."""


@router.post("/api/authors/{author_id}/split", status_code=201)
def split_author(
    author_id: uuid.UUID, body: Split, db: DB, access: CurrentAccess
) -> AuthorRow:
    """These papers are by someone else: a new person, remembered as
    different (matching by name never joins them again)."""
    author = visible_author(db, access, author_id)
    for item_id in body.item_ids:
        get_readable_item(db, access, item_id, write=True)
    try:
        other = authors.split(db, author, body.item_ids, by=access.user.id)
    except authors.Refused as error:
        raise HTTPException(422, str(error)) from error
    return _row(other, _counts(db, access, [other.id]).get(other.id, 0))


class Merge(BaseModel):
    other_id: uuid.UUID
    """The same person: their papers come to this author."""


@router.post("/api/authors/{author_id}/merge")
def merge_authors(
    author_id: uuid.UUID, body: Merge, db: DB, access: CurrentAccess
) -> AuthorRow:
    keep = visible_author(db, access, author_id)
    other = visible_author(db, access, body.other_id)
    _changeable(db, access, keep, other)
    try:
        authors.merge(db, keep, other, by=access.user.id)
    except authors.Refused as error:
        raise HTTPException(409, str(error)) from error
    return _row(keep, _counts(db, access, [keep.id]).get(keep.id, 0))


class Assign(BaseModel):
    author_id: uuid.UUID | None
    """The person; None: someone new of that name."""


@router.put("/api/items/{item_id}/authors/{position}")
def assign_author(
    item_id: uuid.UUID, position: int, body: Assign, db: DB, access: CurrentAccess
) -> AuthorRow:
    """Which person a paper's author is, by hand (later automatic passes
    keep it)."""
    item = get_readable_item(db, access, item_id, write=True)
    authorship = db.get(Authorship, (item.id, position))
    if authorship is None:
        raise HTTPException(404, "no such author on this paper")
    author = (
        visible_author(db, access, body.author_id)
        if body.author_id is not None
        else None
    )
    authors.assign(db, authorship, author)
    linked = db.get(Author, authorship.author_id)
    assert linked is not None
    return _row(linked, _counts(db, access, [linked.id]).get(linked.id, 0))


class LikelyOut(BaseModel):
    one: AuthorRow
    other: AuthorRow
    shared: int
    """Co-authors in common."""


@router.get("/api/authors-suggestions")
def author_suggestions(
    db: DB,
    access: CurrentAccess,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[LikelyOut]:
    """People among the authors of the papers one may change who are
    probably one: the same family name, given names that fit ("M." and
    "Mónica"), not said to be different; most co-authors in common first."""
    pairs = authors.likely_the_same(db, changeable_papers(access), limit=limit)
    ids = {p.one for p in pairs} | {p.other for p in pairs}
    people = {a.id: a for a in db.scalars(select(Author).where(Author.id.in_(ids)))}
    counts = _counts(db, access, list(ids))
    row = lambda i: _row(people[i], counts.get(i, 0))  # noqa: E731
    return [
        LikelyOut(one=row(p.one), other=row(p.other), shared=p.shared) for p in pairs
    ]


class Apart(BaseModel):
    other_id: uuid.UUID


@router.post("/api/authors/{author_id}/apart", status_code=204)
def keep_apart(
    author_id: uuid.UUID, body: Apart, db: DB, access: CurrentAccess
) -> Response:
    """Two people, not one: no longer suggested as the same."""
    one = visible_author(db, access, author_id)
    other = visible_author(db, access, body.other_id)
    if one.id == other.id:
        raise HTTPException(422, "the same person")
    _changeable(db, access, one, other)
    authors.keep_apart(db, one, other, by=access.user.id)
    return Response(status_code=204)


@router.post("/api/author-changes/{change_id}/undo")
def undo_author_change(
    change_id: uuid.UUID, db: DB, access: CurrentAccess
) -> AuthorRow:
    """Take back a split, merge or "different people" (see
    ``authors.undo``): by anyone who may fix that author."""
    change = db.get(AuthorChange, change_id)
    if change is None:
        raise HTTPException(404, "no such change")
    author = visible_author(db, access, change.author_id)
    _changeable(db, access, author)
    try:
        authors.undo(db, change)
    except authors.Refused as error:
        db.rollback()
        raise HTTPException(409, str(error)) from error
    return _row(author, _counts(db, access, [author.id]).get(author.id, 0))
