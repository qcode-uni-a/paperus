"""Open-access PDFs fetched by the server: from arXiv by arXiv ID, and from
Unpaywall's best open location by DOI. Never from publishers' own pages
behind a login (see docs/ingestion.md)."""

import logging
import tempfile
from pathlib import Path

import httpx2

from paperus import pdf
from paperus.identifiers import Scheme
from paperus.models import Item
from paperus.storage import BlobStore, StoredBlob, TooLarge

log = logging.getLogger(__name__)

UNPAYWALL = "https://api.unpaywall.org/v2/"


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


def fetch(
    http: httpx2.Client,
    blobs: BlobStore,
    item: Item,
    *,
    contact_email: str | None,
    max_bytes: int,
) -> StoredBlob:
    """Download the paper's PDF from the first source that gives a whole,
    readable PDF, and store it; NoSource if none does."""
    tried: list[str] = []
    for source in sources(item, contact_email):
        url = source
        if source.startswith("unpaywall:"):
            url = _unpaywall_pdf(http, source.removeprefix("unpaywall:"), contact_email)
            if url is None:
                tried.append(f"{source}: no open-access PDF")
                continue
        try:
            return _download(http, blobs, url, max_bytes)
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
