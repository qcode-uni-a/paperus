"""Papers without a DOI or arXiv ID, found by their title: Crossref is asked
for the best match of the title, first author and year, and only a match
of the same title (case, accents and punctuation aside), the same first
author's family name and a year at most one apart counts. Its DOI comes
with the paper; the paper keeps its own details. With the DOI, OpenAlex
knows its authors (ORCID iDs, see ``paperus.authors``), and open-access
copies and the reference list are found as for any paper.
"""

import logging
from typing import Any

import httpx2

from paperus.authors import fold, written_authors
from paperus.identifiers import InvalidIdentifier, Scheme, implied_by_doi, normalize_doi
from paperus.importing import Export
from paperus.importing.references import PAUSE, Pacer, search_crossref
from paperus.metadata import csl_title

log = logging.getLogger(__name__)

# Shorter titles ("Notes", "Introduction") match too much.
MIN_WORDS = 4
# Not papers, or found otherwise (web pages: by their address).
SKIPPED = {"webpage", "post-weblog", "software", "dataset", "personal_communication"}


def _year(csl: dict[str, Any]) -> int | None:
    for field in ("issued", "published-print", "published-online", "created"):
        try:
            return int(csl[field]["date-parts"][0][0])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return None


def _family(csl: dict[str, Any]) -> str | None:
    found = written_authors(csl)
    return found[0].written.partition(",")[0].strip() if found else None


def matches(found: dict[str, Any], csl: dict[str, Any]) -> bool:
    """Whether Crossref's match is surely this paper (see the module)."""
    titles = found.get("title")
    title = titles[0] if isinstance(titles, list) and titles else titles
    if not isinstance(title, str) or fold(title) != fold(csl_title(csl)):
        return False
    family = _family(csl)
    theirs = _family({"author": found.get("author") or []})
    if family and (theirs is None or fold(theirs) != fold(family)):
        return False
    year, their_year = _year(csl), _year(found)
    return year is None or their_year is None or abs(year - their_year) <= 1


def wanted(csl: dict[str, Any]) -> bool:
    """Whether to look for these details' DOI: a paper, with a long enough
    title."""
    return (
        csl.get("type") not in SKIPPED
        and len(fold(csl_title(csl)).split()) >= MIN_WORDS
    )


def find_doi(http: httpx2.Client, csl: dict[str, Any]) -> str | None:
    """The DOI of the paper these details describe, if Crossref surely
    knows it (see the module)."""
    if not wanted(csl):
        return None
    title = csl_title(csl)
    year = _year(csl)
    query = " ".join(filter(None, [title, _family(csl), str(year) if year else ""]))
    found = search_crossref(http, query)
    if found is None or not matches(found, csl):
        return None
    try:
        return normalize_doi(str(found.get("DOI") or ""))
    except InvalidIdentifier:
        return None


def complete(
    export: Export, http: httpx2.Client | None, *, pause: float | None = None
) -> None:
    """DOIs for the export's papers without a DOI or arXiv ID (see the
    module); without ``http``, nothing is looked up."""
    if http is None:
        return
    pacer = Pacer(PAUSE if pause is None else pause)
    for paper in export.papers:
        known = {scheme for scheme, _ in paper.identifiers}
        if known & {Scheme.DOI, Scheme.ARXIV} or not wanted(paper.csl):
            continue
        pacer()
        doi = find_doi(http, paper.csl)
        if doi is None:
            continue
        log.info("found %s by the title %r", doi, csl_title(paper.csl))
        paper.csl = {**paper.csl, "DOI": doi}
        paper.identifiers = [(Scheme.DOI, doi), *implied_by_doi(doi)]
