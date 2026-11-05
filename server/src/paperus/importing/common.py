"""Helpers shared by the import formats."""

import re
from typing import Any

from paperus.identifiers import (
    InvalidIdentifier,
    Scheme,
    implied_by_doi,
    normalize,
)


def identifiers_of(
    *,
    doi: str | None = None,
    arxiv: str | None = None,
    isbn: str | None = None,
    pmid: str | None = None,
    book: bool = False,
) -> list[tuple[Scheme, str]]:
    """Normalized identifiers for finding the paper again; invalid ones are
    left out. An ISBN counts only for whole books (chapters share theirs)."""
    found: list[tuple[Scheme, str]] = []
    for scheme, value in (
        (Scheme.DOI, doi),
        (Scheme.ARXIV, arxiv),
        (Scheme.ISBN, isbn if book else None),
        (Scheme.PMID, pmid),
    ):
        if not value:
            continue
        try:
            normalized = normalize(scheme, value)
        except InvalidIdentifier:
            continue
        found.append((scheme, normalized))
        if scheme == Scheme.DOI:
            found.extend(implied_by_doi(normalized))
    return list(dict.fromkeys(found))


def date_parts(
    text: str | None = None, year: str | None = None, month: int | None = None
) -> dict[str, Any] | None:
    """CSL date from ``2024-03-02``/``2024-03``/``2024`` or a year (and month);
    unreadable dates are kept as ``raw``."""
    if text:
        found = re.match(r"\s*(\d{4})(?:[-/](\d{1,2}))?(?:[-/](\d{1,2}))?", text)
        if found:
            return {"date-parts": [[int(p) for p in found.groups() if p]]}
        return {"raw": text.strip()}
    if year:
        found = re.search(r"\d{4}", year)
        if not found:
            return {"raw": year.strip()}
        parts = [int(found.group())]
        if month and 1 <= month <= 12:
            parts.append(month)
        return {"date-parts": [parts]}
    return None


def split_keywords(value: str) -> list[str]:
    """``a, b; c`` → ``["a", "b", "c"]`` (commas or semicolons)."""
    parts = re.split(r"\s*[,;]\s*", value.strip())
    return list(dict.fromkeys(p.strip() for p in parts if p.strip()))
