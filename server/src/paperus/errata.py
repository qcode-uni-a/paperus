"""Errata: corrections a journal published to a paper, found at Crossref
and added to the paper as versions of their own kind ("erratum": their
own DOIs, details and PDFs; never the version cited or shown).

Most publishers' corrections say which paper they correct (Crossref's
``update-to``): ``filter=updates:<DOI>`` finds them, one request a paper
(Nature's, IOP's, Elsevier's, Springer's). APS's say it only in their
title ("Erratum: <title> [Phys. Rev. A 108, 063502 (2023)]"): looked up by
the paper's title among APS's, and taken when the citation in brackets
has the paper's volume and article number.

Rarely: a weekly job (``paperus.jobs``) looks at a few hundred papers with
a journal's DOI, each when it has one, then every half year while it is
less than three years old (errata come within a year or two), never
after that.
"""

import logging
import re
from datetime import UTC, datetime, timedelta

import httpx2
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from paperus import item_references, library, metadata
from paperus.identifiers import Scheme, is_arxiv_doi, normalize
from paperus.item_references import SourceUnavailable
from paperus.models import Identifier, Item, MetadataSource, Version, VersionKind

log = logging.getLogger(__name__)

CROSSREF = "https://api.crossref.org/works"
PER_RUN = 300
RECHECK = timedelta(days=182)
RECENT = timedelta(days=3 * 365)
# Crossref's update types of a correction (not a retraction, a new version).
CORRECTIONS = {"erratum", "correction", "corrigendum"}
APS = "10.1103/"
_TAGS = re.compile(r"<[^>]+>")
_BRACKETS = re.compile(r"\[([^\]]*)\]")


def waiting(
    db: Session, limit: int = PER_RUN, now: datetime | None = None
) -> list[Item]:
    """Papers with a journal's DOI never looked at, then those published in
    the last three years not looked at for half a year."""
    now = now or datetime.now(UTC)
    with_doi = (
        select(Version.item_id)
        .join(Identifier)
        .where(
            Identifier.scheme == Scheme.DOI,
            ~Identifier.value.ilike("10.48550/%"),
            Version.kind != VersionKind.ERRATUM,
        )
    )
    checked = Item.errata_checked_at
    return list(
        db.scalars(
            select(Item)
            .where(
                Item.deleted_at.is_(None),
                Item.id.in_(with_doi),
                or_(
                    checked.is_(None),
                    and_(
                        checked < now - RECHECK,
                        Item.issued_to >= (now - RECENT).date(),
                    ),
                ),
            )
            .order_by(checked.asc().nulls_first(), Item.id)
            .limit(limit)
        )
    )


def journal_doi(item: Item) -> str | None:
    """The paper's DOI of a journal (not arXiv's), the cited version's first."""
    preferred = library.preferred_version(item)
    for version in sorted(item.versions, key=lambda v: v is not preferred):
        if version.kind == VersionKind.ERRATUM:
            continue
        for identifier in version.identifiers:
            if identifier.scheme == Scheme.DOI and not is_arxiv_doi(identifier.value):
                return identifier.value
    return None


def _get(
    http: httpx2.Client, params: dict[str, str], contact_email: str | None
) -> list[dict[str, object]]:
    item_references.PACERS.crossref()  # shared with the reference lists
    if contact_email:
        params = {**params, "mailto": contact_email}
    try:
        response = http.get(CROSSREF, params=params, timeout=30)
        response.raise_for_status()
        items = response.json()["message"]["items"]
    except (httpx2.HTTPError, ValueError, KeyError, TypeError) as error:
        raise SourceUnavailable(f"Crossref did not answer: {error}") from error
    return [w for w in items if isinstance(w, dict)]


# What a correction's record needs for its citation.
FIELDS = ",".join(
    (
        "DOI",
        "title",
        "update-to",
        "container-title",
        "short-container-title",
        "volume",
        "page",
        "article-number",
        "issued",
    )
)


def _title(work: dict[str, object]) -> str:
    titles = work.get("title")
    title = titles[0] if isinstance(titles, list) and titles else ""
    return " ".join(_TAGS.sub("", str(title)).split())


def cited(work: dict[str, object]) -> str:
    """The correction as cited: "Erratum: Phys. Rev. B 96, 199902 (2017)";
    by its title without its journal's details."""

    def first(name: str) -> str:
        value = work.get(name)
        return str(
            value[0] if isinstance(value, list) and value else value or ""
        ).strip()

    journal = first("short-container-title") or first("container-title")
    number = str(work.get("article-number") or work.get("page") or "").strip()
    issued = work.get("issued")
    parts = issued.get("date-parts") if isinstance(issued, dict) else None
    year = parts[0][0] if isinstance(parts, list) and parts and parts[0] else None
    volume = str(work.get("volume") or "").strip()
    if not (journal and volume):
        return _title(work) or "Erratum"
    where = f"{journal} {volume}" + (f", {number}" if number else "")
    return f"Erratum: {where}" + (f" ({year})" if year else "")


def find(
    http: httpx2.Client, item: Item, doi: str, contact_email: str | None = None
) -> list[tuple[str, str]]:
    """The corrections of the paper: (their DOI, how they are cited). Raises
    ``SourceUnavailable`` if Crossref does not answer."""
    found: dict[str, str] = {}
    works = _get(
        http,
        {"filter": f"updates:{doi}", "select": FIELDS, "rows": "20"},
        contact_email,
    )
    for work in works:
        updates = work.get("update-to")
        if not isinstance(updates, list):
            continue
        for update in updates:
            if (
                isinstance(update, dict)
                and str(update.get("DOI", "")).lower() == doi.lower()
                and str(update.get("type", "")).lower() in CORRECTIONS
            ):
                found[str(work["DOI"]).lower()] = cited(work)
    if doi.lower().startswith(APS):
        found |= _aps(http, item, doi, contact_email)
    return sorted(found.items())


def _aps(
    http: httpx2.Client, item: Item, doi: str, contact_email: str | None
) -> dict[str, str]:
    """APS's errata, by the paper's title and the citation in theirs."""
    version = next(
        (
            v
            for v in item.versions
            if any(i.value.lower() == doi.lower() for i in v.identifiers)
        ),
        None,
    )
    csl = version.csl if version is not None else {}
    volume = str(csl.get("volume") or "").strip()
    number = str(csl.get("article-number") or csl.get("page") or "").split("-")[0]
    title = " ".join(_TAGS.sub("", item.title or "").split())
    if not (volume and number.strip() and title):
        return {}
    params = {
        "query.bibliographic": f"Erratum {title}",
        "filter": "prefix:10.1103"
        + (f",from-pub-date:{item.year}" if item.year else ""),
        "select": FIELDS,
        "rows": "5",
    }
    citation = re.compile(rf"\b{re.escape(volume)}\s*,\s*{re.escape(number.strip())}\b")
    found = {}
    for work in _get(http, params, contact_email):
        erratum = _title(work)
        if erratum.lower().startswith("erratum") and any(
            citation.search(part) for part in _BRACKETS.findall(erratum)
        ):
            found[str(work["DOI"]).lower()] = cited(work)
    return found


def check(
    db: Session,
    http: httpx2.Client,
    items: list[Item],
    contact_email: str | None = None,
    now: datetime | None = None,
) -> int:
    """Look for the papers' errata and add those found as their versions
    (kind "erratum", with their DOIs and details); how many papers got one.
    A paper Crossref did not answer for is looked at again next time."""
    now = now or datetime.now(UTC)
    with_errata = 0
    for item in items:
        doi = journal_doi(item)
        try:
            found = find(http, item, doi, contact_email) if doi else []
        except SourceUnavailable as error:
            log.info("errata of %s: %s", item.id, error)
            continue
        if any([add(db, http, item, erratum, cited) for erratum, cited in found]):
            with_errata += 1
        item.errata_checked_at = now
        db.commit()
    return with_errata


def add(db: Session, http: httpx2.Client, item: Item, doi: str, cited: str) -> bool:
    """The erratum of this DOI as the paper's version, with its details from
    its registry (else just how it is cited); whether it was new. One the
    paper or another paper has already is left as it is."""
    known = {i.value.lower() for v in item.versions for i in v.identifiers}
    if doi.lower() in known:
        return False
    try:
        value = normalize(Scheme.DOI, doi)
        csl, _ = metadata.lookup_doi(http, value)
    except ValueError:
        return False
    except (metadata.DOINotFound, metadata.MetadataUnavailable):
        csl = {"type": "article-journal", "title": cited, "DOI": doi}
    try:
        with db.begin_nested():
            library.add_version(
                db,
                item,
                kind=VersionKind.ERRATUM,
                label=None,
                csl=csl,
                source=MetadataSource.LOOKUP,
                identifiers=[(Scheme.DOI, value)],
                created_by=None,
            )
    except library.IdentifierTaken:
        log.info("erratum %s of %s is a paper of its own", value, item.id)
        return False
    log.info("erratum of %s: %s", item.id, value)
    return True
