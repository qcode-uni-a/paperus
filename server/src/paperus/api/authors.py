"""Authors as people (``paperus.authors``): who they are, their papers the
person may see, their co-authors and where they were; and the fixes by
hand: split, merge, and which person a paper's author is.

Author records are shared by the installation, but a person learns of an
author only through papers they may see: an author without such papers
does not exist for them.
"""

import uuid
from collections import Counter
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, aliased

from paperus import authors
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.api.items import ItemOut, get_readable_item, item_out
from paperus.models import Author, Authorship, Item

router = APIRouter(tags=["authors"])


class AuthorRow(BaseModel):
    id: uuid.UUID
    name: str
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


def _visible(access: Access) -> list[ColumnElement[bool]]:
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
        .where(Authorship.author_id.in_(author_ids), *_visible(access))
        .group_by(Authorship.author_id)
    )
    return {author_id: count for author_id, count in rows if author_id is not None}


def _row(author: Author, papers: int) -> AuthorRow:
    return AuthorRow(id=author.id, name=author.name, papers=papers, orcid=author.orcid)


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
        .where(*_visible(access))
        .group_by(Author.id)
    )
    for word in authors.fold(q or "").split():
        query = query.where(Author.key.contains(word, autoescape=True))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    response.headers["X-Total-Count"] = str(total)
    order = (
        [papers.desc(), Author.key] if sort == "papers" else [Author.key, papers.desc()]
    )
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
            .where(Authorship.author_id == author.id, *_visible(access))
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
                *_visible(access),
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
        papers=len(item_ids),
        orcid=author.orcid,
        openalex_id=author.openalex_id,
        spellings=[name for name, _ in spellings.most_common()],
        coauthors=[_row(named[i], together[i]) for i in coauthor_ids if i in named],
        affiliations=affiliations,
        namesakes=[_row(a, counts[a.id]) for a in namesakes if a.id in counts],
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
    """Authors of the person's papers not linked to anyone: a name several
    people share, with nothing to tell which one."""
    rows = list(
        db.execute(
            select(Authorship, Item)
            .join(Item, Item.id == Authorship.item_id)
            .where(Authorship.author_id.is_(None), *_visible(access))
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
            candidates=[
                _row(p, counts.get(p.id, 0)) for p in people if p.key == authorship.key
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
        get_readable_item(db, access, item_id)
    try:
        other = authors.split(db, author, body.item_ids)
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
    try:
        authors.merge(db, keep, other)
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
    item = get_readable_item(db, access, item_id)
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
