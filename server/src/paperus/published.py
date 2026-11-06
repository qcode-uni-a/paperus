"""Published versions of preprints, found by themselves: arXiv's record of
a paper (the journal DOI its authors entered), else OpenAlex (which links a
preprint with its journal version). A version found is added to the paper,
which then shows and cites it; its PDF is missing until open access, the
browser extension or an upload brings it (Manage → Missing).

Sources compared in docs/ingestion.md; on one physicist's library arXiv
knew the journal DOI of 42 of 130 preprints, OpenAlex of a quarter of the
rest. OpenAlex merges works by heuristics, so a version is added only if
its title matches the preprint's.
"""

import logging
import re
import time
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher

import httpx2
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from paperus import library, metadata
from paperus.identifiers import Scheme, implied_by_doi, is_arxiv_doi, normalize
from paperus.models import (
    Identifier,
    Item,
    MetadataSource,
    Version,
    VersionKind,
)

log = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
OPENALEX = "https://api.openalex.org/works/doi:"
# arXiv asks for at most one request every three seconds.
ARXIV_PAUSE = 3.0
ARXIV_BATCH = 50
RECHECK = timedelta(days=30)
# Titles at least this alike (0-1) count as the same paper.
SAME_TITLE = 0.8
SHARED_WORDS = 0.5

JOURNAL = (VersionKind.PUBLISHED, VersionKind.ACCEPTED)
_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.DOTALL)
_ENTRY_ID = re.compile(r"<id>https?://arxiv\.org/abs/([^<]+?)(?:v\d+)?</id>")
_ENTRY_DOI = re.compile(r"<arxiv:doi[^>]*>([^<]+)</arxiv:doi>")


def waiting(db: Session, limit: int, now: datetime | None = None) -> list[Item]:
    """Preprints (with an arXiv ID, without a journal version) not checked
    in the last month, never checked first."""
    now = now or datetime.now(UTC)
    with_arxiv = (
        select(Version.item_id)
        .join(Identifier)
        .where(Identifier.scheme == Scheme.ARXIV)
    )
    journal = select(Version.item_id).where(Version.kind.in_(JOURNAL))
    return list(
        db.scalars(
            select(Item)
            .where(
                Item.deleted_at.is_(None),
                Item.id.in_(with_arxiv),
                Item.id.not_in(journal),
                or_(
                    Item.published_checked_at.is_(None),
                    Item.published_checked_at < now - RECHECK,
                ),
            )
            .order_by(Item.published_checked_at.asc().nulls_first(), Item.id)
            .limit(limit)
        ).unique()
    )


def arxiv_id(item: Item) -> str | None:
    for version in item.versions:
        for identifier in version.identifiers:
            if identifier.scheme == Scheme.ARXIV:
                return identifier.value
    return None


def arxiv_dois(http: httpx2.Client, ids: list[str]) -> dict[str, str]:
    """The journal DOIs arXiv knows for these papers (one request)."""
    if not ids:
        return {}
    try:
        response = http.get(
            ARXIV_API,
            params={"id_list": ",".join(ids), "max_results": len(ids)},
            timeout=60,
        )
    except httpx2.HTTPError as error:
        log.info("arXiv did not answer: %s", error)
        return {}
    if response.status_code != 200:
        return {}
    found = {}
    for entry in _ENTRY.findall(response.text):
        paper, doi = _ENTRY_ID.search(entry), _ENTRY_DOI.search(entry)
        if paper and doi:
            found[paper.group(1)] = doi.group(1).strip()
    return found


def openalex_doi(
    http: httpx2.Client, paper: str, contact_email: str | None
) -> str | None:
    """The journal DOI OpenAlex gives the work of an arXiv paper, if any."""
    params = {"select": "doi"}
    if contact_email:
        params["mailto"] = contact_email
    try:
        response = http.get(
            f"{OPENALEX}10.48550/arxiv.{paper}", params=params, timeout=15
        )
    except httpx2.HTTPError:
        return None
    if response.status_code != 200:
        return None
    doi = str((response.json() or {}).get("doi") or "").removeprefix("https://doi.org/")
    return doi if doi and not is_arxiv_doi(doi) else None


def _alike(a: str, b: str) -> bool:
    """The same paper's titles: nearly the same text, or (a paper renamed
    on publication) at least half of the longer words shared."""

    def plain(text: str) -> str:
        return re.sub(r"[^\w]+", " ", text.lower()).strip()

    first, second = plain(a), plain(b)
    if SequenceMatcher(None, first, second).ratio() >= SAME_TITLE:
        return True
    words = {w for w in first.split() if len(w) >= 4}
    others = {w for w in second.split() if len(w) >= 4}
    return len(words & others) >= SHARED_WORDS * max(1, len(words | others))


def add_published(
    db: Session, http: httpx2.Client, item: Item, doi: str, source: str
) -> Version | None:
    """The journal version of this DOI, added to the paper if its details
    are found and its title matches; None otherwise (also when another
    paper has the DOI: the two show up as duplicates by their titles)."""
    try:
        value = normalize(Scheme.DOI, doi)
        csl, kind = metadata.lookup_doi(http, value)
    except (ValueError, metadata.DOINotFound, metadata.MetadataUnavailable):
        return None
    if kind not in JOURNAL or not _alike(metadata.csl_title(csl), item.title):
        log.info("not taken for %s: %s (%s)", item.id, value, source)
        return None
    try:
        with db.begin_nested():
            version = library.add_version(
                db,
                item,
                kind=kind,
                label=None,
                csl=csl,
                source=MetadataSource.LOOKUP,
                identifiers=[(Scheme.DOI, value), *implied_by_doi(value)],
                created_by=None,
            )
    except library.IdentifierTaken:
        return None
    log.info("published version of %s found via %s: %s", item.id, source, value)
    return version


def check(
    db: Session,
    http: httpx2.Client,
    items: list[Item],
    *,
    contact_email: str | None,
    pause: float = ARXIV_PAUSE,
) -> list[Item]:
    """Look for these preprints' published versions and add those found;
    every paper is marked as checked. Commits; returns the papers that got
    one."""
    upgraded = []
    for start in range(0, len(items), ARXIV_BATCH):
        batch = items[start : start + ARXIV_BATCH]
        ids = {item.id: arxiv_id(item) for item in batch}
        if start:
            time.sleep(pause)
        known = arxiv_dois(http, [i for i in ids.values() if i])
        for item in batch:
            paper = ids[item.id]
            doi, source = known.get(paper or ""), "arXiv"
            if doi is None and paper:
                doi, source = openalex_doi(http, paper, contact_email), "OpenAlex"
            if doi and add_published(db, http, item, doi, source):
                upgraded.append(item)
            item.published_checked_at = datetime.now(UTC)
            db.commit()
    return upgraded
