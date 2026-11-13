"""How often papers are cited, as OpenAlex counts: each paper with a DOI
looked up when new and then each week, 50 a request (an hourly job,
``paperus.jobs``). Shown on a paper's page and as a way to sort; a paper
passing a milestone (10, 50, 100, … citations) is celebrated for those of
its authors here (``notifications.milestone``). The first count only sets
where one starts: nothing is celebrated for what came before.

OpenAlex counts citations by all papers it knows (not only this library's),
a little behind and below Google Scholar's. A paper with several DOIs (its
preprint's, its journal's) has the highest of their counts.
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx2
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from paperus import item_references, notifications
from paperus.identifiers import Scheme
from paperus.item_references import SourceUnavailable
from paperus.models import Identifier, Item, Version, VersionKind

log = logging.getLogger(__name__)

OPENALEX = "https://api.openalex.org/works"
BATCH = 50
"""DOIs a request (OpenAlex's most for one filter)."""
PER_RUN = 1000
RECHECK = timedelta(days=7)
MILESTONES = (10, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


def waiting(
    db: Session, limit: int = PER_RUN, now: datetime | None = None
) -> list[Item]:
    """Papers with a DOI never counted, then those counted a week ago."""
    now = now or datetime.now(UTC)
    with_doi = (
        select(Version.item_id)
        .join(Identifier)
        .where(Identifier.scheme == Scheme.DOI, Version.kind != VersionKind.ERRATUM)
    )
    checked = Item.citations_checked_at
    return list(
        db.scalars(
            select(Item)
            .where(
                Item.deleted_at.is_(None),
                Item.id.in_(with_doi),
                or_(checked.is_(None), checked < now - RECHECK),
            )
            .order_by(checked.asc().nulls_first(), Item.id)
            .limit(limit)
        )
    )


def _dois(item: Item) -> list[str]:
    return [
        identifier.value.lower()
        for version in item.versions
        if version.kind != VersionKind.ERRATUM
        for identifier in version.identifiers
        if identifier.scheme == Scheme.DOI
    ]


def counts(
    http: httpx2.Client, dois: list[str], contact_email: str | None = None
) -> dict[str, int]:
    """OpenAlex's citation count of each DOI it knows (lower case). Raises
    ``SourceUnavailable`` if it does not answer."""
    item_references.PACERS.openalex()
    params = {
        "filter": "doi:" + "|".join(dois),
        "select": "doi,cited_by_count",
        "per-page": str(BATCH),
    }
    if contact_email:
        params["mailto"] = contact_email
    try:
        response = http.get(OPENALEX, params=params, timeout=30)
        response.raise_for_status()
        results = response.json()["results"]
    except (httpx2.HTTPError, ValueError, KeyError, TypeError) as error:
        raise SourceUnavailable(f"OpenAlex did not answer: {error}") from error
    found: dict[str, int] = {}
    for work in results:
        if not isinstance(work, dict):
            continue
        doi = str(work.get("doi") or "").removeprefix("https://doi.org/").lower()
        count = work.get("cited_by_count")
        if doi and isinstance(count, int):
            found[doi] = max(count, found.get(doi, 0))
    return found


def check(
    db: Session,
    http: httpx2.Client,
    items: list[Item],
    contact_email: str | None = None,
    now: datetime | None = None,
) -> int:
    """Count the papers' citations; commits per request; how many papers
    OpenAlex knew. Papers it does not answer for wait for the next run."""
    now = now or datetime.now(UTC)
    known = 0
    batch: list[tuple[Item, list[str]]] = []
    dois: list[str] = []
    for item in items:
        own = _dois(item)
        if len(dois) + len(own) > BATCH:
            known += _count(db, http, batch, dois, contact_email, now)
            batch, dois = [], []
        batch.append((item, own))
        dois += own[:BATCH]
    if batch:
        known += _count(db, http, batch, dois, contact_email, now)
    return known


def _count(
    db: Session,
    http: httpx2.Client,
    batch: list[tuple[Item, list[str]]],
    dois: list[str],
    contact_email: str | None,
    now: datetime,
) -> int:
    try:
        found = counts(http, dois, contact_email)
    except SourceUnavailable as error:
        log.info("citation counts: %s", error)
        return 0
    known = 0
    for item, own in batch:
        values: dict[str, object] = {"citations_checked_at": now}
        new = max((found[d] for d in own if d in found), default=None)
        if new is not None:
            known += 1
            old = item.cited_by_count
            values["cited_by_count"] = new
            passed = [m for m in MILESTONES if old is not None and old < m <= new]
            if passed:
                notifications.milestone(db, item, passed[-1], new)
        # Not a change of the paper's own (its lists' order, devices' sync).
        db.execute(update(Item).where(Item.id == item.id).values(**values))
    db.commit()
    return known
