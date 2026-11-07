"""Completing the references of a LaTeX reference list (``bbl``) online.

A reference with a DOI or arXiv ID gets its metadata from the registry, as a
paper added by its DOI does (Crossref/DataCite via doi.org; arXiv IDs by
their arXiv DOI). One without is searched on Crossref by its text and taken
only if the match is certain: Crossref's score of at least ``MIN_SCORE``,
its first author's name in the reference, and its title in the reference
too (or, for physics styles that print no titles, its year, volume and
first page). What is still unknown is not added: free text alone is not a
paper. It is listed in the report ("Not recognised: …") instead.
"""

import logging
import re
import time
import unicodedata
from typing import Any

import httpx2

from paperus import metadata
from paperus.identifiers import InvalidIdentifier, Scheme, normalize_doi
from paperus.identify import title_appears
from paperus.importing import Export
from paperus.importing.bbl import Reference
from paperus.importing.common import identifiers_of

log = logging.getLogger(__name__)

CROSSREF = "https://api.crossref.org/works"
# Crossref's relevance score of its best match. Checked on six real
# references (2026-11): the right matches scored 85-109, the best matches for
# references Crossref does not have (a made-up one, a private communication,
# a book reprint) 20-32. The checks of author, title or numbers come on top.
MIN_SCORE = 60.0
# Between two requests: Crossref's public pool allows a few per second.
PAUSE = 0.2
SHORT = 120


def complete(
    export: Export, http: httpx2.Client | None, *, pause: float | None = None
) -> None:
    """Metadata for the export's references (none looked up without
    ``http``); references still unknown are dropped and listed as problems."""
    pacer = Pacer(PAUSE if pause is None else pause)
    kept = []
    for paper in export.papers:
        if not isinstance(paper, Reference):
            kept.append(paper)
            continue
        if http is not None:
            _complete(paper, http, pacer)
        # A reference with fields (BibLaTeX, REVTeX) and a title is as good
        # as a BibTeX entry; free text without identifier is not.
        if paper.identifiers or (paper.style != "plain" and paper.has_title):
            if not paper.has_title:
                paper.csl["title"] = short(paper.text) or "(untitled)"
            kept.append(paper)
        else:
            export.problems.append(
                f"Not recognised: {short(paper.text) or paper.source_key}"
            )
    export.papers = kept


def short(text: str) -> str:
    """The start of a reference, for messages."""
    text = " ".join(text.split())
    if len(text) <= SHORT:
        return text
    return text[:SHORT].rsplit(" ", 1)[0] + " …"


class Pacer:
    """Waits between requests (not before the first); one per service, so
    requests to it keep their distance."""

    def __init__(self, pause: float) -> None:
        self.pause = pause
        self.last: float | None = None

    def __call__(self) -> None:
        if self.last is not None:
            time.sleep(max(0.0, self.last + self.pause - time.monotonic()))
        self.last = time.monotonic()


def _complete(paper: Reference, http: httpx2.Client, pacer: Pacer) -> None:
    dois = [v for s, v in paper.identifiers if s == Scheme.DOI]
    dois += [f"10.48550/arxiv.{v}" for s, v in paper.identifiers if s == Scheme.ARXIV]
    for doi in dict.fromkeys(dois):
        pacer()
        try:
            csl, _ = metadata.lookup_doi(http, doi)
        except (metadata.DOINotFound, metadata.MetadataUnavailable):
            log.info("no metadata for %s (reference %s)", doi, paper.source_key)
            continue
        _take(paper, csl, doi)
        return
    if paper.identifiers or not paper.text:
        return  # what the reference list says is kept
    pacer()
    found = search_crossref(http, paper.text)
    if found is None or not confident(found, paper.text):
        return
    try:
        doi = normalize_doi(str(found.get("DOI") or ""))
    except InvalidIdentifier:
        return
    pacer()
    try:
        csl, _ = metadata.lookup_doi(http, doi)
    except (metadata.DOINotFound, metadata.MetadataUnavailable):
        csl = {
            **paper.csl,
            "title": _first(found.get("title")) or paper.csl.get("title"),
        }
    _take(paper, csl, doi)


def _take(paper: Reference, csl: dict[str, Any], doi: str) -> None:
    """The registry's metadata for the paper; the DOI it came by first."""
    paper.csl = {**csl, "citation-key": paper.source_key}
    paper.looked_up = True
    paper.identifiers = list(
        dict.fromkeys([*identifiers_of(doi=doi), *paper.identifiers])
    )


def search_crossref(http: httpx2.Client, text: str) -> dict[str, Any] | None:
    """Crossref's best match for a reference's text, if any."""
    try:
        response = http.get(
            CROSSREF,
            params={
                "query.bibliographic": text[:1000],
                "rows": 1,
                "select": "DOI,title,author,issued,container-title,volume,page,score",
            },
            timeout=30,
        )
    except httpx2.HTTPError as error:
        log.info("Crossref did not answer: %s", error)
        return None
    if response.status_code != 200:
        return None
    try:
        items = response.json()["message"]["items"]
    except (ValueError, KeyError, TypeError):
        return None
    return items[0] if items and isinstance(items[0], dict) else None


def confident(found: dict[str, Any], text: str) -> bool:
    """Whether Crossref's match is surely the reference (see the module)."""
    try:
        score = float(found.get("score") or 0)
    except (TypeError, ValueError):
        return False
    if score < MIN_SCORE:
        return False
    words = set(_words(text))
    authors = found.get("author")
    first = authors[0] if isinstance(authors, list) and authors else None
    family = (
        first.get("family") or first.get("name") if isinstance(first, dict) else None
    )
    if family and not set(_words(str(family))) <= words:
        return False
    title = _first(found.get("title"))
    if title and title_appears(_fold(title), _fold(text)):
        return True
    # Styles without titles (Phys. Rev.): the numbers must agree.
    year = _year(found)
    page = str(found.get("page") or "").split("-")[0]
    details = [str(year or ""), str(found.get("volume") or ""), page]
    return all(details) and all(set(_words(d)) <= words for d in details)


def _first(value: object) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, str) and value else None


def _year(found: dict[str, Any]) -> int | None:
    try:
        return int(found["issued"]["date-parts"][0][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _fold(text: str) -> str:
    """Lowercase without accents: "Müller" and "Muller" are alike."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", _fold(text))
