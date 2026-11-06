"""Open-access PDFs fetched by the server: from arXiv by arXiv ID, and from
Unpaywall's best open location by DOI. Never from publishers' own pages
behind a login (see docs/ingestion.md). OpenAlex says whether a paper known
by its DOI is on arXiv too."""

import logging
import re
import tempfile
from pathlib import Path
from typing import Any

import httpx2

from paperus import pdf
from paperus.identifiers import Scheme
from paperus.models import Item
from paperus.storage import BlobStore, StoredBlob, TooLarge

log = logging.getLogger(__name__)

UNPAYWALL = "https://api.unpaywall.org/v2/"
OPENALEX = "https://api.openalex.org/works/doi:"
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/(.+?)(?:v\d+)?(?:\.pdf)?/?$")


class NoSource(Exception):
    """No open-access PDF is known for the paper."""


def sources(item: Item, contact_email: str | None) -> list[str]:
    """Where an open-access PDF of the paper may be: arXiv first, then
    Unpaywall (asked only with a contact email, as it requires one)."""
    found: list[str] = []
    for version in item.versions:
        for identifier in version.identifiers:
            if identifier.scheme == Scheme.ARXIV:
                found.append(f"https://arxiv.org/pdf/{identifier.value}")
    if contact_email:
        for version in item.versions:
            for identifier in version.identifiers:
                if identifier.scheme == Scheme.DOI and not identifier.value.startswith(
                    "10.48550/"
                ):
                    found.append(f"unpaywall:{identifier.value}")
    return list(dict.fromkeys(found))


def _openalex_locations(
    http: httpx2.Client, doi: str, contact_email: str | None
) -> list[dict[str, Any]]:
    """Where OpenAlex knows the paper with this DOI to be (the publisher,
    arXiv, repositories), each with its version and whether it is open;
    empty if OpenAlex does not know it or does not answer."""
    params = {"select": "locations"}
    if contact_email:
        params["mailto"] = contact_email  # OpenAlex's "polite pool"
    try:
        response = http.get(f"{OPENALEX}{doi}", params=params, timeout=15)
    except httpx2.HTTPError as error:
        log.info("OpenAlex did not answer for %s: %s", doi, error)
        return []
    if response.status_code != 200:
        return []
    locations = (response.json() or {}).get("locations") or []
    return [location for location in locations if isinstance(location, dict)]


def arxiv_id_for(
    http: httpx2.Client, doi: str, contact_email: str | None
) -> str | None:
    """The arXiv ID of the paper with this DOI, if OpenAlex lists an arXiv
    copy among where the paper is."""
    for location in _openalex_locations(http, doi, contact_email):
        for key in ("landing_page_url", "pdf_url"):
            match = _ARXIV_URL.search(str(location.get(key) or ""))
            if match:
                return match.group(1)
    return None


def arxiv_id_of(url: str) -> str | None:
    """The arXiv ID in an arXiv address (abs or pdf)."""
    match = _ARXIV_URL.search(url)
    return match.group(1) if match else None


def fetch(
    http: httpx2.Client,
    blobs: BlobStore,
    item: Item,
    *,
    contact_email: str | None,
    max_bytes: int,
) -> tuple[StoredBlob, str]:
    """Download the paper's PDF from the first source that gives a whole,
    readable PDF, and store it; returns it with the address it came from.
    NoSource if none does."""
    tried: list[str] = []
    for source in sources(item, contact_email):
        url = source
        if source.startswith("unpaywall:"):
            url = _unpaywall_pdf(http, source.removeprefix("unpaywall:"), contact_email)
            if url is None:
                tried.append(f"{source}: no open-access PDF")
                continue
        try:
            return _download(http, blobs, url, max_bytes), url
        except (httpx2.HTTPError, pdf.PdfError, TooLarge, ValueError) as error:
            log.info("no PDF from %s: %s", url, error)
            tried.append(f"{url}: {error}")
    raise NoSource("; ".join(tried) or "no open-access source is known for this paper")


def _unpaywall_pdf(http: httpx2.Client, doi: str, email: str | None) -> str | None:
    response = http.get(f"{UNPAYWALL}{doi}", params={"email": email}, timeout=15)
    if response.status_code != 200:
        return None
    best = (response.json() or {}).get("best_oa_location") or {}
    url = best.get("url_for_pdf")
    return url if isinstance(url, str) and url.startswith("https://") else None


JOURNAL_VERSIONS = ("publishedVersion", "acceptedVersion")


def fetch_journal_copy(
    http: httpx2.Client,
    blobs: BlobStore,
    doi: str,
    *,
    contact_email: str | None,
    max_bytes: int,
) -> StoredBlob:
    """The journal's own open copy of a published paper (the published or
    accepted version, never a preprint): from where OpenAlex lists one, else
    Unpaywall (with the contact email). NoSource if none gives a whole PDF;
    publishers often refuse downloads by servers even of open papers (the
    browser extension gets those)."""
    urls = [
        location.get("pdf_url")
        for location in _openalex_locations(http, doi, contact_email)
        if location.get("is_oa") and location.get("version") in JOURNAL_VERSIONS
    ]
    if contact_email:
        params = {"email": contact_email}
        response = http.get(f"{UNPAYWALL}{doi}", params=params, timeout=15)
        if response.status_code == 200:
            urls += [
                location.get("url_for_pdf")
                for location in (response.json() or {}).get("oa_locations") or []
                if location.get("version") in JOURNAL_VERSIONS
            ]
    tried: list[str] = []
    for url in dict.fromkeys(u for u in urls if isinstance(u, str)):
        if not url.startswith("https://"):
            continue
        try:
            return _download(http, blobs, url, max_bytes)
        except (httpx2.HTTPError, pdf.PdfError, TooLarge, ValueError) as error:
            log.info("no PDF from %s: %s", url, error)
            tried.append(f"{url}: {error}")
    if not tried and not contact_email:
        raise NoSource(
            "no open copy of the journal's version is known (Unpaywall would be "
            "asked with the contact email set)"
        )
    raise NoSource("; ".join(tried) or "no open copy of the journal's version")


def _download(
    http: httpx2.Client, blobs: BlobStore, url: str, max_bytes: int
) -> StoredBlob:
    """Into a temporary file first: only a whole PDF that opens is stored."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "download.pdf"
        size = 0
        with http.stream("GET", url, timeout=60, follow_redirects=True) as response:
            response.raise_for_status()
            with path.open("wb") as out:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise TooLarge(max_bytes)
                    out.write(chunk)
        with path.open("rb") as stream:
            if not stream.read(5).startswith(b"%PDF-"):
                raise ValueError("not a PDF (probably a web page)")
        pdf.pages(path)  # opens completely, or raises PdfError
        with path.open("rb") as stream:
            return blobs.put(
                iter(lambda: stream.read(1024 * 1024), b""), max_size=max_bytes
            )
