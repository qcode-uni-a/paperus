"""Papers' reference lists, and the papers in the library that cite a paper.

A paper's list is looked for in the background (``paperus.jobs``), best
source first:

1. a paper with an arXiv ID: arXiv's LaTeX source, read as the import of
   LaTeX sources reads it (its ``.bbl``, else ``thebibliography``, else the
   cited entries of its ``.bib``);
2. a paper with a DOI: Crossref's record of it, with the references the
   publisher deposited (most publishers do, not all);
3. else the PDF's own reference list, from its stored text: split into
   references where they are numbered (``[12]`` or ``12.``, counted up from
   1), else, best effort, where an author-year entry starts (``Smith, J.``
   after the end of the previous one). Lists in other layouts (initials
   first, ``1)``) are not split, and a page's running head may end up in a
   reference.

Only identifiers are taken in the background (no searching): DOIs, arXiv
IDs and links in the references. A reference without one is kept as text;
the person can ask Crossref for it (``find``), with the import's check that
the match is certain.
"""

import html
import logging
import re
import tempfile
import uuid
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

import httpx2
from sqlalchemy import and_, delete, exists, insert, or_, select, update
from sqlalchemy.orm import Session

from paperus import library, notifications
from paperus.access import Access
from paperus.identifiers import (
    InvalidIdentifier,
    Scheme,
    implied_by_doi,
    is_arxiv_doi,
    normalize,
)
from paperus.importing import Export, ExportedPaper
from paperus.importing.apply import Files as FileSource
from paperus.importing.apply import NoFiles
from paperus.importing.bbl import Reference, identifiers_in
from paperus.importing.references import Pacer, confident, search_crossref
from paperus.importing.run import (
    NotAnExport,
    into_collection,
    open_upload,
    read_opened,
)
from paperus.models import (
    Chunk,
    File,
    FileChunk,
    Identifier,
    Item,
    ItemReference,
    TextStatus,
    Version,
    VersionKind,
)

log = logging.getLogger(__name__)

E_PRINT = "https://arxiv.org/e-print/"
CROSSREF = "https://api.crossref.org/works/"
OPENALEX = "https://api.openalex.org/works"
# Works OpenAlex answers for in one request (its filter takes 50 values).
OPENALEX_BATCH = 50
# An arXiv source with its figures is a few MB, rarely 100.
MAX_E_PRINT_BYTES = 100 * 2**20
# A list read from a PDF has at least this many references.
MIN_PDF_REFERENCES = 3
# Longer texts are cut (a reference is a few hundred characters).
MAX_TEXT = 2000
MAX_FIELD = 500
# Papers looked at per run of the background job.
PER_RUN = 40

SOURCES = ("arxiv", "crossref", "pdf")


class SourceUnavailable(Exception):
    """arXiv or Crossref did not answer: the paper is looked at again later."""


class NeedsArxiv(Exception):
    """The list is to come from arXiv, not asked here: the job goes on in
    the queue of arXiv's lookups (``paperus.jobs``), with its pauses."""


@dataclass
class Pacers:
    """Pauses between requests to arXiv (it asks for 3 s) and Crossref."""

    arxiv: Pacer = field(default_factory=lambda: Pacer(3.0))
    crossref: Pacer = field(default_factory=lambda: Pacer(0.2))
    openalex: Pacer = field(default_factory=lambda: Pacer(0.2))


# Shared by the worker's jobs, so one paper after another keeps the pauses.
PACERS = Pacers()


@dataclass
class Found:
    """One reference, before it is stored."""

    text: str
    title: str | None = None
    authors: str | None = None
    year: int | None = None
    container: str | None = None
    doi: str | None = None
    arxiv: str | None = None
    url: str | None = None


def _normal(scheme: Scheme, value: str | None) -> str | None:
    if not value:
        return None
    try:
        return normalize(scheme, value)
    except InvalidIdentifier:
        return None


def _cut(value: str | None, length: int = MAX_FIELD) -> str | None:
    value = " ".join(value.split()) if value else None
    return value[:length] if value else None


def _found(
    text: str,
    *,
    title: str | None = None,
    authors: str | None = None,
    year: int | None = None,
    container: str | None = None,
    doi: str | None = None,
    arxiv: str | None = None,
    url: str | None = None,
) -> Found:
    """A reference with its identifiers normalized (an arXiv DOI gives the
    arXiv ID) and its fields cut to size."""
    doi = _normal(Scheme.DOI, doi)
    arxiv = _normal(Scheme.ARXIV, arxiv)
    if doi and arxiv is None:
        arxiv = next((v for _, v in implied_by_doi(doi)), None)
    return Found(
        text=_cut(text, MAX_TEXT) or "",
        title=_cut(title),
        authors=_cut(authors, 200),
        year=year if year and 1000 <= year <= 2999 else None,
        container=_cut(container),
        doi=doi,
        arxiv=arxiv,
        url=_cut(url, 1000),
    )


def short_authors(names: list[str]) -> str | None:
    """ "Smith", "Smith and Jones", "Smith et al."."""
    names = [n for n in names if n]
    if len(names) <= 2:
        return " and ".join(names) or None
    return f"{names[0]} et al."


# --- arXiv: the LaTeX source -------------------------------------------------


def _first(value: object) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, str) and value else None


def from_paper(paper: ExportedPaper) -> Found:
    """A reference read from a LaTeX source (``.bbl`` or ``.bib``)."""
    csl = paper.csl
    title = _first(csl.get("title"))
    if title == "(untitled)":
        title = None
    names = [
        str(a.get("family") or a.get("literal") or "")
        for a in csl.get("author") or []
        if isinstance(a, dict)
    ]
    container = _first(csl.get("container-title"))
    year = library.issued_year(csl)
    identifiers = dict(paper.identifiers)
    text = paper.text if isinstance(paper, Reference) else ""
    if not text:
        # A .bib entry: its fields as a reference would print them.
        text = ". ".join(
            str(part)
            for part in (", ".join(names), title, container, csl.get("volume"), year)
            if part
        )
    return _found(
        text or title or "",
        title=title,
        authors=short_authors(names),
        year=year,
        container=container,
        doi=identifiers.get(Scheme.DOI),
        arxiv=identifiers.get(Scheme.ARXIV),
        url=_first(csl.get("URL")),
    )


def from_arxiv(http: httpx2.Client, paper: str, pacers: Pacers) -> list[Found]:
    """The references of an arXiv paper's LaTeX source; empty if it has
    none (or arXiv has only a PDF)."""
    pacers.arxiv()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "e-print"
        try:
            with http.stream("GET", E_PRINT + paper, timeout=120) as response:
                if response.status_code == 404:
                    return []
                if response.status_code != 200:
                    raise SourceUnavailable(f"arXiv answered {response.status_code}")
                size = 0
                with path.open("wb") as file:
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_E_PRINT_BYTES:
                            log.info("arXiv source of %s is too large", paper)
                            return []
                        file.write(chunk)
        except httpx2.HTTPError as error:
            raise SourceUnavailable(f"arXiv did not answer: {error}") from error
        with path.open("rb") as file:
            if file.read(4) == b"%PDF":
                return []
        try:
            with open_upload(path, f"arXiv:{paper}") as opened:
                export = read_opened(opened) if opened.latex else Export("none")
        except NotAnExport:
            return []
    return [from_paper(p) for p in export.papers]


# --- Crossref: the references publishers deposit ------------------------------

_TAGS = re.compile(r"<[^>]+>")


def _year(value: object) -> int | None:
    found = re.match(r"\s*([12]\d{3})", str(value or ""))
    return int(found.group(1)) if found else None


def from_crossref(
    http: httpx2.Client, doi: str, pacers: Pacers, contact_email: str | None = None
) -> list[Found]:
    """The references Crossref has for a DOI (empty if none)."""
    pacers.crossref()
    params = {"mailto": contact_email} if contact_email else None
    try:
        response = http.get(CROSSREF + doi, params=params, timeout=30)
    except httpx2.HTTPError as error:
        raise SourceUnavailable(f"Crossref did not answer: {error}") from error
    if response.status_code == 404:
        return []
    if response.status_code != 200:
        raise SourceUnavailable(f"Crossref answered {response.status_code}")
    try:
        entries = response.json()["message"].get("reference") or []
    except (ValueError, KeyError, TypeError, AttributeError):
        return []
    found = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = entry.get("article-title") or entry.get("volume-title")
        container = entry.get("journal-title") or entry.get("series-title")
        author = entry.get("author")
        year = _year(entry.get("year"))
        text = html.unescape(_TAGS.sub("", str(entry.get("unstructured") or "")))
        if not text.strip():
            parts = (
                author,
                title,
                container,
                entry.get("volume"),
                entry.get("first-page"),
                f"({year})" if year else None,
            )
            text = ", ".join(str(p) for p in parts if p)
        in_text, arxiv, url = identifiers_in(text)
        doi_of_entry = entry.get("DOI") or in_text
        if not text.strip():
            text = f"doi:{doi_of_entry}" if doi_of_entry else ""
        if not text.strip():
            continue
        found.append(
            _found(
                text,
                title=title,
                authors=author,
                year=year,
                container=container,
                doi=doi_of_entry,
                arxiv=arxiv,
                url=url,
            )
        )
    return found


# --- the PDF: its stored text --------------------------------------------------


def _numbered(text: str, marker: Callable[[int], re.Pattern[str]]) -> list[str]:
    """The pieces between markers 1, 2, 3, … (each the first after the one
    before)."""
    starts: list[tuple[int, int]] = []
    position, number = 0, 1
    while found := marker(number).search(text, position):
        starts.append((found.start(), found.end()))
        position, number = found.end(), number + 1
    if not starts:
        return []
    ends = [start for start, _ in starts[1:]] + [len(text)]
    pairs = zip(starts, ends, strict=True)
    return [text[end:until].strip() for (_, end), until in pairs]


def _bracketed(number: int) -> re.Pattern[str]:
    return re.compile(rf"\[{number}\]")


def _dotted(number: int) -> re.Pattern[str]:
    # "12. A. Smith": not "Phys. Rev. 12, …" or "pp. 1-12. ".
    return re.compile(
        rf"(?:^|(?<=\s)){number}\.\s+(?=[A-Z\"'(\u201c\u2018]|[a-z]+ [A-Z])"
    )


def _glued(number: int) -> re.Pattern[str]:
    # AIP's "12S. Probst", and "12 S. Probst": the number before initials.
    return re.compile(rf"(?:^|(?<=\s)){number} ?(?=[A-Z]\.\s?[A-Z-])")


_YEAR = re.compile(r"(?<![\d./-])(1[6-9]\d\d|20\d\d)(?![\d/-])")
_LINK = re.compile(r"(?:https?://|doi:\s*|\b10\.\d{4,9}/)\S+", re.IGNORECASE)
# An author-year entry's start: "Smith, J.", "van der Berg, A. B.", "Smith-Jones, K.".
_AUTHOR_START = re.compile(
    r"(?<=\s)(?:(?:van|von|de|der|den|di|da|du|del|la|le)\s+)*"
    r"[A-Z][\w'\u2019-]+(?:\s[A-Z][\w'\u2019-]+)?,\s+(?:[A-Z]\.\s?-?)+(?=[\s,&(])"
)
# Words after which a name belongs to the same reference: joining words,
# and initials ("W. De Roeck, F. Huveneers": the second author's name).
_JOINING = {"and", "&", "by", "in", "in:", "eds.", "ed.", "und", "with"}
_INITIALS = re.compile(r"^(?:[A-Z][a-z]?\.-?)+$")


def _year_in(text: str) -> int | None:
    found = _YEAR.search(_LINK.sub(" ", text))
    return int(found.group(1)) if found else None


def _author_year(text: str) -> list[str]:
    """Pieces starting at "Surname, I." where the text before ended a
    reference (not after a comma or "and"); a piece without a year joins
    the one before."""
    cuts = [0]
    for found in _AUTHOR_START.finditer(text):
        before = text[: found.start()].rstrip()
        last = before.rsplit(None, 1)[-1].lower() if before else ""
        if (
            before
            and not before.endswith((",", ";", ":"))
            and last not in _JOINING
            and not _INITIALS.match(before.rsplit(None, 1)[-1])
        ):
            cuts.append(found.start())
    pieces: list[str] = []
    for start, end in zip(cuts, [*cuts[1:], len(text)], strict=True):
        piece = text[start:end].strip()
        if pieces and _year_in(piece) is None:
            pieces[-1] = f"{pieces[-1]} {piece}"
        elif piece:
            pieces.append(piece)
    # What comes before the first entry (the heading) is no reference.
    if pieces and not _AUTHOR_START.match(" " + pieces[0][:200], 1):
        pieces = pieces[1:]
    return pieces


def split_references(text: str) -> list[str]:
    """A reference section's text (from a PDF) in single references; empty
    if it cannot be split reliably (see the module)."""
    text = " ".join(text.split())
    for split in (
        lambda t: _numbered(t, _bracketed),
        lambda t: _numbered(t, _dotted),
        lambda t: _numbered(t, _glued),
        _author_year,
    ):
        pieces = [p for p in split(text) if p]
        lengths = [len(p) for p in pieces]
        if len(pieces) >= MIN_PDF_REFERENCES and median(lengths) >= 30:
            # The last one runs on to the end of the section: cut it.
            longest = max(500, 3 * int(median(lengths)))
            if len(pieces[-1]) > longest:
                pieces[-1] = pieces[-1][:longest].rsplit(" ", 1)[0] + " …"
            return pieces
    return []


def reference_text(db: Session, item: Item) -> str:
    """The reference section of the paper's file (the preferred version's
    first, main files first), from its stored passages."""
    preferred = library.preferred_version(item)
    versions = sorted(item.versions, key=lambda v: v is not preferred)
    for version in versions:
        files = sorted(version.files, key=lambda f: (f.role != "main", f.id))
        for file in files:
            if file.deleted_at is not None or file.text_status != TextStatus.DONE:
                continue
            passages = db.scalars(
                select(Chunk.text)
                .join(FileChunk, FileChunk.chunk_sha256 == Chunk.sha256)
                .where(FileChunk.file_id == file.id, FileChunk.in_references)
                .order_by(FileChunk.position)
            ).all()
            if passages:
                return " ".join(passages)
    return ""


# Publishers' download notes in every page's margin ("Downloaded from
# https://…/doi/10.1002/… by …"): their links are the paper's own.
_DOWNLOADED = re.compile(r"\bDownloaded from\s+\S+", re.IGNORECASE)


def from_pdf(db: Session, item: Item) -> list[Found]:
    own = {i.value for v in item.versions for i in v.identifiers}
    found = []
    for piece in split_references(_DOWNLOADED.sub(" ", reference_text(db, item))):
        doi, arxiv, url = identifiers_in(piece)
        if _normal(Scheme.DOI, doi) in own:
            doi = None  # a paper does not cite itself: a running head's DOI
        found.append(_found(piece, year=_year_in(piece), doi=doi, arxiv=arxiv, url=url))
    return found


# --- looking, storing ---------------------------------------------------------


def _identifier(item: Item, scheme: Scheme) -> str | None:
    """The paper's identifier of this scheme, the preferred version's first;
    DOIs of arXiv papers do not count (Crossref has no references for them)."""
    preferred = library.preferred_version(item)
    for version in sorted(item.versions, key=lambda v: v is not preferred):
        if version.kind == VersionKind.ERRATUM:
            continue  # its own references, not the paper's
        for identifier in version.identifiers:
            if identifier.scheme == scheme and not (
                scheme == Scheme.DOI and is_arxiv_doi(identifier.value)
            ):
                return identifier.value
    return None


def look(
    db: Session,
    http: httpx2.Client,
    item: Item,
    *,
    contact_email: str | None = None,
    pacers: Pacers | None = None,
    arxiv: bool = True,
) -> tuple[str | None, list[Found]]:
    """The paper's reference list and where it came from; (None, []) if
    none is found. A journal's paper: Crossref first (on our papers as
    complete as the LaTeX source, its references more often with a DOI,
    and no 3 s pause or download); then arXiv's source, unless not
    ``arxiv`` (then ``NeedsArxiv``); then the PDF's text. Raises
    ``SourceUnavailable``."""
    pacers = pacers or PACERS
    doi = _identifier(item, Scheme.DOI)
    # arXiv's own DOIs (DataCite) have no reference lists at Crossref.
    journal = doi if doi and not doi.lower().startswith("10.48550/") else None
    if journal and (found := from_crossref(http, journal, pacers, contact_email)):
        return "crossref", found
    if paper := _identifier(item, Scheme.ARXIV):
        if not arxiv:
            raise NeedsArxiv(paper)
        if found := from_arxiv(http, paper, pacers):
            return "arxiv", found
    if found := from_pdf(db, item):
        return "pdf", found
    return None, []


def fill_details(
    http: httpx2.Client,
    found: list[Found],
    *,
    contact_email: str | None = None,
    pacers: Pacers | None = None,
) -> None:
    """Title, authors, year and journal from OpenAlex for references known
    only by their DOI or arXiv ID (as some publishers deposit them at
    Crossref), 50 to a request. Without an answer they stay as they are."""
    pacers = pacers or PACERS
    bare: dict[str, list[Found]] = {}
    for reference in found:
        if reference.title:
            continue
        doi = reference.doi or (
            f"10.48550/arxiv.{reference.arxiv}" if reference.arxiv else None
        )
        if doi:
            bare.setdefault(doi.lower(), []).append(reference)
    dois = list(bare)
    for start in range(0, len(dois), OPENALEX_BATCH):
        batch = dois[start : start + OPENALEX_BATCH]
        params = {
            "filter": "doi:" + "|".join(batch),
            "per-page": str(OPENALEX_BATCH),
            "select": "doi,title,publication_year,authorships,primary_location",
        }
        if contact_email:
            params["mailto"] = contact_email
        pacers.openalex()
        try:
            response = http.get(OPENALEX, params=params, timeout=20)
            response.raise_for_status()
            works = response.json().get("results") or []
        except (httpx2.HTTPError, ValueError) as error:
            log.info("no details from OpenAlex: %s", error)
            continue
        for work in works:
            doi = str(work.get("doi") or "").removeprefix("https://doi.org/").lower()
            for reference in bare.get(doi, []):
                _take_work(reference, work)


def _take_work(reference: Found, work: dict[str, Any]) -> None:
    names = [
        str((authorship.get("author") or {}).get("display_name") or "").split()[-1:]
        for authorship in work.get("authorships") or []
    ]
    source = ((work.get("primary_location") or {}).get("source")) or {}
    reference.title = _cut(work.get("title"))
    reference.authors = _cut(short_authors([n[0] for n in names if n]), 200)
    year = work.get("publication_year")
    reference.year = year if isinstance(year, int) and 1000 <= year <= 2999 else None
    reference.container = _cut(source.get("display_name"))


def store(
    db: Session, item_id: uuid.UUID, source: str | None, found: list[Found]
) -> None:
    """Keep the list found (a list found before stays if none is found now)
    and when it was looked for. Without stamping a change on the paper:
    its own details did not change."""
    values: dict[str, Any] = {"references_checked_at": datetime.now(UTC)}
    if found:
        db.execute(delete(ItemReference).where(ItemReference.item_id == item_id))
        db.execute(
            insert(ItemReference),
            [
                {"item_id": item_id, "position": n, **vars(reference)}
                for n, reference in enumerate(found, 1)
            ],
        )
        values["references_source"] = source
    db.execute(update(Item).where(Item.id == item_id).values(**values))
    citing = db.get(Item, item_id) if found else None
    if citing is not None:
        # Papers of people here it cites: celebrated (a paper new here).
        notifications.cited(
            db,
            citing,
            {r.doi for r in found if r.doi},
            {r.arxiv for r in found if r.arxiv},
        )
    db.commit()


def check(
    db: Session,
    http: httpx2.Client,
    item: Item,
    *,
    contact_email: str | None = None,
    pacers: Pacers | None = None,
    arxiv: bool = True,
) -> int | None:
    """Look for the paper's list and store it; the number of references
    found, None if a source did not answer (then it is looked at again
    later). ``NeedsArxiv`` if it is to come from arXiv, not ``arxiv``."""
    try:
        source, found = look(
            db, http, item, contact_email=contact_email, pacers=pacers, arxiv=arxiv
        )
    except SourceUnavailable as error:
        log.info("reference list of %s: %s", item.id, error)
        db.rollback()
        return None
    fill_details(http, found, contact_email=contact_email, pacers=pacers)
    store(db, item.id, source, found)
    log.info("reference list of %s: %d from %s", item.id, len(found), source)
    return len(found)


def waiting(db: Session, limit: int = PER_RUN) -> list[Item]:
    """Papers to look at: never looked at, oldest first; then those without
    a list that got a version or file since."""
    checked = Item.references_checked_at
    newer_version = exists().where(
        Version.item_id == Item.id, Version.created_at > checked
    )
    newer_file = exists(
        select(File.id)
        .join(Version)
        .where(Version.item_id == Item.id, File.created_at > checked)
    )
    return list(
        db.scalars(
            select(Item)
            .where(
                Item.deleted_at.is_(None),
                or_(
                    checked.is_(None),
                    and_(
                        Item.references_source.is_(None),
                        or_(newer_version, newer_file),
                    ),
                ),
            )
            .order_by(checked.asc().nulls_first(), Item.id)
            .limit(limit)
        )
    )


# --- reading: matched to the library ------------------------------------------


def references_of(
    db: Session, access: Access, item: Item, *, only: int | None = None
) -> list[tuple[ItemReference, Item | None]]:
    """The paper's references in order (``only`` the one at this position),
    each with the paper the person can see that has its DOI or arXiv ID
    (not in the trash; archived ones too, as adding it would find them)."""
    query = select(ItemReference).where(ItemReference.item_id == item.id)
    if only is not None:
        query = query.where(ItemReference.position == only)
    rows = list(db.scalars(query.order_by(ItemReference.position)))
    matched = _matches(
        db,
        access,
        {r.doi for r in rows if r.doi},
        {r.arxiv for r in rows if r.arxiv},
        but=item.id,
    )
    return [
        (
            row,
            matched.get((Scheme.DOI, row.doi))
            or matched.get((Scheme.ARXIV, row.arxiv)),
        )
        for row in rows
    ]


def _matches(
    db: Session,
    access: Access,
    dois: set[str],
    arxivs: set[str],
    *,
    but: uuid.UUID,
) -> dict[tuple[str, str | None], Item]:
    if not dois and not arxivs:
        return {}
    rows = db.execute(
        select(Identifier.scheme, Identifier.value, Version.item_id)
        .join(Version, Version.id == Identifier.version_id)
        .join(Item, Item.id == Version.item_id)
        .where(
            or_(
                and_(Identifier.scheme == Scheme.DOI, Identifier.value.in_(dois)),
                and_(Identifier.scheme == Scheme.ARXIV, Identifier.value.in_(arxivs)),
            ),
            access.item_filter(),
            Item.deleted_at.is_(None),
            Item.id != but,
        )
        .order_by(Identifier.id)
    ).all()
    items = {
        i.id: i
        for i in db.scalars(select(Item).where(Item.id.in_({r.item_id for r in rows})))
    }
    found: dict[tuple[str, str | None], Item] = {}
    for scheme, value, item_id in rows:
        found.setdefault((scheme, value), items[item_id])
    return found


def citing(db: Session, access: Access, item: Item) -> list[Item]:
    """Papers the person can see (not in the trash or archive) whose
    references have one of this paper's DOIs or arXiv IDs; newest first."""
    identifiers = [i for v in item.versions for i in v.identifiers]
    dois = [i.value for i in identifiers if i.scheme == Scheme.DOI]
    arxivs = [i.value for i in identifiers if i.scheme == Scheme.ARXIV]
    if not dois and not arxivs:
        return []
    cites = select(ItemReference.item_id).where(
        or_(ItemReference.doi.in_(dois), ItemReference.arxiv.in_(arxivs))
    )
    return list(
        db.scalars(
            select(Item)
            .where(
                Item.id.in_(cites),
                Item.id != item.id,
                access.item_filter(),
                Item.deleted_at.is_(None),
                Item.archived_at.is_(None),
            )
            .order_by(Item.year.desc().nulls_last(), Item.title)
        )
    )


# --- finding one on Crossref, importing them all -------------------------------


def find(
    db: Session, http: httpx2.Client, reference: ItemReference
) -> ItemReference | None:
    """Crossref's match for a reference without identifier, taken (its DOI,
    and title, year and journal where missing) if certain; else None. A
    reference with an identifier is returned as it is."""
    if reference.doi or reference.arxiv:
        return reference
    match = search_crossref(http, reference.text)
    if match is None or not confident(match, reference.text):
        return None
    doi = _normal(Scheme.DOI, str(match.get("DOI") or ""))
    if doi is None:
        return None
    taken = _found(
        reference.text,
        title=_first(match.get("title")),
        year=_year((match.get("issued") or {}).get("date-parts", [[None]])[0][0]),
        container=_first(match.get("container-title")),
        doi=doi,
    )
    reference.doi = taken.doi
    reference.arxiv = taken.arxiv
    reference.title = reference.title or taken.title
    reference.year = reference.year or taken.year
    reference.container = reference.container or taken.container
    db.commit()
    return reference


def to_import(rows: Iterable[ItemReference]) -> list[Reference]:
    """The references with a DOI or arXiv ID, as the import of a LaTeX
    source has them (looked up by ``paperus.importing.references``)."""
    papers = []
    for row in rows:
        identifiers = [
            *([(Scheme.DOI, row.doi)] if row.doi else []),
            *([(Scheme.ARXIV, row.arxiv)] if row.arxiv else []),
        ]
        if not identifiers:
            continue
        csl: dict[str, Any] = {
            "type": "article-journal" if row.container else "article"
        }
        if row.title:
            csl["title"] = row.title
        if row.container:
            csl["container-title"] = row.container
        if row.year:
            csl["issued"] = {"date-parts": [[row.year]]}
        papers.append(
            Reference(
                csl=csl,
                identifiers=identifiers,
                source_key=f"[{row.position}]",
                text=row.text,
            )
        )
    return papers


@contextmanager
def reading_for_import(
    db: Session,
    access: Access,
    item_id: uuid.UUID,
    complete: Callable[[Export], None],
) -> Generator[tuple[Export, FileSource]]:
    """The paper's references with identifiers as an export (for
    ``paperus.importing.run.run_export``), into a collection named after
    the paper."""
    item = db.get(Item, item_id)
    if item is None or item.deleted_at is not None or not access.can_read_item(item):
        raise NotAnExport("The paper is no longer there.")
    rows = db.scalars(
        select(ItemReference)
        .where(ItemReference.item_id == item_id)
        .order_by(ItemReference.position)
    )
    export = Export(format="references", papers=list(to_import(rows)))
    complete(export)
    if export.papers:
        into_collection(export, collection_name(item.title))
    yield export, NoFiles()


def collection_name(title: str) -> str:
    return f"References of {title}"[:200]
