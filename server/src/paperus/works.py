"""A person's works as OpenAlex knows them, by their ORCID iD or OpenAlex
author id: to add those not in the library yet (an author's page; one's
own papers under Manage → Missing). Only works with a DOI, as papers are
added by it; the newest first. OpenAlex often lists a paper more than once
(the journal's, arXiv's, a repository's copy): those of the same title are
one work, under the journal's DOI.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx2

from paperus.authors import fold
from paperus.identifiers import InvalidIdentifier, normalize_doi

log = logging.getLogger(__name__)

OPENALEX = "https://api.openalex.org/works"
# OpenAlex's most per page; enough for nearly everyone's list.
LIMIT = 200
# Not papers of their own.
LEFT_OUT = {"paratext", "erratum", "peer-review", "retraction", "editorial", "letter"}


# DOIs of copies rather than of the paper itself: arXiv, SSRN, Zenodo,
# ResearchGate, figshare; the journal's comes first.
COPIES = ("10.48550/", "10.2139/", "10.5281/", "10.13140/", "10.6084/")


def _rank(doi: str) -> int:
    return next((i + 1 for i, p in enumerate(COPIES) if doi.startswith(p)), 0)


class Unavailable(RuntimeError):
    """OpenAlex did not answer."""


@dataclass
class Work:
    doi: str
    title: str
    year: int | None
    journal: str | None
    copies: list[str]
    """The DOIs of its other copies (arXiv's, a repository's)."""


def _work(entry: dict[str, Any]) -> Work | None:
    if entry.get("type") in LEFT_OUT:
        return None
    try:
        doi = normalize_doi(str(entry.get("doi") or ""))
    except InvalidIdentifier:
        return None
    source = (entry.get("primary_location") or {}).get("source") or {}
    year = entry.get("publication_year")
    return Work(
        doi=doi,
        title=str(entry.get("title") or doi),
        year=year if isinstance(year, int) else None,
        journal=source.get("display_name") or None,
        copies=[],
    )


def works_of(
    http: httpx2.Client,
    *,
    orcid: str | None = None,
    openalex_id: str | None = None,
    contact_email: str | None = None,
) -> list[Work]:
    """The person's works with a DOI, newest first (one request; nothing
    without an id). Raises ``Unavailable``."""
    if orcid:
        wanted = f"author.orcid:https://orcid.org/{orcid}"
    elif openalex_id:
        wanted = f"author.id:{openalex_id}"
    else:
        return []
    params = {
        "filter": wanted,
        "per-page": str(LIMIT),
        "sort": "publication_year:desc",
        "select": "doi,title,publication_year,primary_location,type",
    }
    if contact_email:
        params["mailto"] = contact_email
    try:
        response = http.get(OPENALEX, params=params, timeout=30)
        response.raise_for_status()
        entries = response.json().get("results") or []
    except (httpx2.HTTPError, ValueError) as error:
        log.info("no works from OpenAlex: %s", error)
        raise Unavailable(str(error)) from error
    by_title: dict[str, list[Work]] = {}
    seen: set[str] = set()
    for entry in entries:
        work = _work(entry) if isinstance(entry, dict) else None
        if work is not None and work.doi not in seen:
            seen.add(work.doi)
            by_title.setdefault(fold(work.title) or work.doi, []).append(work)
    found = []
    for same in by_title.values():
        same.sort(key=lambda w: _rank(w.doi))
        first = same[0]
        first.copies = [w.doi for w in same[1:] if w.doi != first.doi]
        first.year = first.year or next((w.year for w in same if w.year), None)
        found.append(first)
    return sorted(found, key=lambda w: -(w.year or 0))
