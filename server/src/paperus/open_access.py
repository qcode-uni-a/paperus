"""Open-access PDFs fetched by the server: from arXiv by arXiv ID, and by DOI
from the open copies OpenAlex and Unpaywall list (repositories before
publishers). Never from publishers' own pages
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


# How a download larger than the upload limit is noted.
TOO_LARGE = "larger than the upload limit"


class NoSource(Exception):
    """No open-access PDF is known for the paper."""


def sources(item: Item, contact_email: str | None) -> list[str]:
    """Where an open-access PDF of the paper may be: arXiv first, then the
    open copies OpenAlex and Unpaywall list for its DOI (``doi:…``;
    Unpaywall is asked only with a contact email, as it requires one)."""
    found: list[str] = []
    for version in item.versions:
        for identifier in version.identifiers:
            if identifier.scheme == Scheme.ARXIV:
                found.append(f"https://arxiv.org/pdf/{identifier.value}")
    for version in item.versions:
        for identifier in version.identifiers:
            if identifier.scheme == Scheme.DOI and not identifier.value.startswith(
                "10.48550/"
            ):
                found.append(f"doi:{identifier.value}")
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


# The file name a site gives a download.
_CONTENT_NAME = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)


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
) -> tuple[StoredBlob, str, str | None]:
    """Download the paper's PDF from the first source that gives a whole,
    readable PDF, and store it; returns it with the address it came from and
    the name the site gave it (arXiv's names its version: "2401.12345v3.pdf"),
    if any. NoSource if none does."""
    tried: list[str] = []
    for source in sources(item, contact_email):
        urls = [source]
        if source.startswith("doi:"):
            urls = open_copies(http, source.removeprefix("doi:"), contact_email)
            if not urls:
                tried.append(f"{source}: no open-access PDF")
                continue
        for url in urls:
            try:
                stored, name = _download(http, blobs, url, max_bytes)
                return stored, url, name
            except (httpx2.HTTPError, pdf.PdfError, TooLarge, ValueError) as error:
                log.info("no PDF from %s: %s", url, error)
                tried.append(
                    f"{url}: {TOO_LARGE if isinstance(error, TooLarge) else error}"
                )
    raise NoSource("; ".join(tried) or "no open-access source is known for this paper")


def open_copies(http: httpx2.Client, doi: str, contact_email: str | None) -> list[str]:
    """Every open PDF of the paper that OpenAlex or Unpaywall lists, arXiv
    first, then repositories (a university's, a funder's), the publisher
    last: publishers often refuse servers, so one refusing copy does not
    end the search. Unpaywall only with a contact email."""
    found: list[tuple[int, object]] = []
    for location in _openalex_locations(http, doi, contact_email):
        source = location.get("source") or {}
        if location.get("is_oa"):
            kind = source.get("type") if isinstance(source, dict) else None
            found.append(
                (_rank(location.get("pdf_url"), kind), location.get("pdf_url"))
            )
    if contact_email:
        for location in _unpaywall_locations(http, doi, contact_email):
            kind = location.get("host_type")
            found.append(
                (_rank(location.get("url_for_pdf"), kind), location.get("url_for_pdf"))
            )
    urls = [
        url
        for _, url in sorted(found, key=lambda pair: pair[0])
        if isinstance(url, str) and url.startswith("https://")
    ]
    return list(dict.fromkeys(urls))


def refused(error: str | None) -> list[str]:
    """The copies a try noted as refusing the download or giving a web page
    (``url: reason; …``, as ``fetch`` notes them): open, so a browser may
    still get them where the server may not."""
    return [
        url
        for url, reason in re.findall(r"(https://[^\s;]+): ([^;]*)", error or "")
        if re.search(r"\b40[13]\b|not a PDF", reason)
    ]


def _rank(url: object, kind: object) -> int:
    if isinstance(url, str) and _ARXIV_URL.search(url):
        return 0
    return 1 if kind == "repository" else 2


def _unpaywall_locations(
    http: httpx2.Client, doi: str, email: str
) -> list[dict[str, Any]]:
    """Unpaywall's open copies of the paper, its best first."""
    try:
        response = http.get(f"{UNPAYWALL}{doi}", params={"email": email}, timeout=15)
    except httpx2.HTTPError as error:
        log.info("Unpaywall did not answer for %s: %s", doi, error)
        return []
    if response.status_code != 200:
        return []
    found = response.json() or {}
    best = found.get("best_oa_location")
    locations = [best, *(found.get("oa_locations") or [])]
    return [location for location in locations if isinstance(location, dict)]


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
            return _download(http, blobs, url, max_bytes)[0]
        except (httpx2.HTTPError, pdf.PdfError, TooLarge, ValueError) as error:
            log.info("no PDF from %s: %s", url, error)
            tried.append(
                f"{url}: {TOO_LARGE if isinstance(error, TooLarge) else error}"
            )
    if not tried and not contact_email:
        raise NoSource(
            "no open copy of the journal's version is known (Unpaywall would be "
            "asked with the contact email set)"
        )
    raise NoSource("; ".join(tried) or "no open copy of the journal's version")


def _download(
    http: httpx2.Client, blobs: BlobStore, url: str, max_bytes: int
) -> tuple[StoredBlob, str | None]:
    """Into a temporary file first: only a whole PDF that opens is stored;
    with the name the site gives it (Content-Disposition), if any."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "download.pdf"
        size = 0
        with http.stream("GET", url, timeout=60, follow_redirects=True) as response:
            response.raise_for_status()
            named = _CONTENT_NAME.search(
                response.headers.get("content-disposition", "")
            )
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
            stored = blobs.put(
                iter(lambda: stream.read(1024 * 1024), b""), max_size=max_bytes
            )
        name = Path(named.group(1)).name if named else None
        return stored, (name or None)
