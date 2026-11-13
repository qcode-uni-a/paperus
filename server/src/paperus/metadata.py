"""Bibliographic metadata from DOIs."""

from typing import Any

import httpx2

from paperus import __version__, mathml
from paperus.config import Settings
from paperus.identifiers import is_arxiv_doi
from paperus.models import VersionKind


class DOINotFound(LookupError):
    pass


class MetadataUnavailable(RuntimeError):
    """The registry could not be reached or returned something unusable."""


def user_agent(contact_email: str | None) -> str:
    """Crossref and others ask clients to name themselves and a contact."""
    agent = f"paperus/{__version__}"
    return f"{agent} (mailto:{contact_email})" if contact_email else agent


OPENALEX_HOST = "api.openalex.org"
_openalex_key: str | None = None


def use_openalex_key(key: str | None) -> None:
    """OpenAlex's API key, sent with every request to it from here on (this
    process's clients made by ``make_http_client``)."""
    global _openalex_key
    _openalex_key = key or None


def _with_openalex_key(request: httpx2.Request) -> None:
    if _openalex_key and request.url.host == OPENALEX_HOST:
        request.headers["Authorization"] = f"Bearer {_openalex_key}"


def make_http_client(settings: Settings) -> httpx2.Client:
    return httpx2.Client(
        headers={"User-Agent": user_agent(settings.contact_email)},
        timeout=20,
        follow_redirects=True,
        event_hooks={"request": [_with_openalex_key]},
    )


def fetch_csl(client: httpx2.Client, doi: str) -> dict[str, Any]:
    """CSL-JSON for a DOI via content negotiation at doi.org."""
    try:
        response = client.get(
            f"https://doi.org/{doi}",
            headers={"Accept": "application/vnd.citationstyles.csl+json"},
        )
    except httpx2.HTTPError as error:
        raise MetadataUnavailable(str(error)) from error
    if response.status_code == 404:
        raise DOINotFound(doi)
    if response.status_code != 200:
        raise MetadataUnavailable(f"doi.org answered {response.status_code}")
    try:
        csl = response.json()
    except ValueError as error:
        raise MetadataUnavailable("doi.org did not return JSON") from error
    if not isinstance(csl, dict):
        raise MetadataUnavailable("doi.org did not return a CSL-JSON object")
    for key in ("title", "subtitle", "original-title"):
        value = csl.get(key)
        if isinstance(value, str):
            csl[key] = mathml.to_tex(value)
        elif isinstance(value, list):
            csl[key] = [mathml.to_tex(v) if isinstance(v, str) else v for v in value]
    return csl


# Crossref's content negotiation returns its own type names, not CSL's.
_CROSSREF_TO_CSL_TYPE = {
    "journal-article": "article-journal",
    "proceedings-article": "paper-conference",
    "book-chapter": "chapter",
    "book-section": "chapter",
    "book-part": "chapter",
    "monograph": "book",
    "edited-book": "book",
    "reference-book": "book",
    "book-set": "book",
    "book-track": "book",
    "posted-content": "article",
    "dissertation": "thesis",
    "report-component": "report",
    "standard": "standard",
    "peer-review": "review",
    "reference-entry": "entry",
    "component": "article",
    "other": "document",
}


def csl_type(csl: dict[str, Any]) -> str:
    value = str(csl.get("type") or "document")
    return _CROSSREF_TO_CSL_TYPE.get(value, value)


def csl_title(csl: dict[str, Any]) -> str:
    title = csl.get("title")
    if isinstance(title, list):
        title = title[0] if title else None
    return title if isinstance(title, str) and title else "(untitled)"


def version_kind(doi: str, csl: dict[str, Any]) -> VersionKind:
    """Guess the kind of version a DOI's metadata describes."""
    if is_arxiv_doi(doi) or csl.get("subtype") == "preprint":
        return VersionKind.PREPRINT
    if csl.get("type") == "posted-content":
        return VersionKind.PREPRINT
    return VersionKind.PUBLISHED


def lookup_doi(
    client: httpx2.Client, doi: str, kind: VersionKind | None = None
) -> tuple[dict[str, Any], VersionKind]:
    """CSL-JSON and version kind for a DOI (raises DOINotFound, MetadataUnavailable)."""
    csl = fetch_csl(client, doi)
    kind = kind or version_kind(doi, csl)
    if kind == VersionKind.PREPRINT:
        # CSL's type for preprints; arXiv reports "article-journal".
        csl = {**csl, "type": "article"}
    return csl, kind
