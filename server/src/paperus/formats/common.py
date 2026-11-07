"""Helpers shared by the writers."""

import re
from dataclasses import dataclass, field
from typing import Any

from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedPaper


@dataclass
class Written:
    """One file for another reference manager."""

    content: bytes
    filename: str
    """A name for it, e.g. ``paperus.bib``."""
    media_type: str
    warnings: list[str] = field(default_factory=list)
    """What the format cannot hold, in plain words for the person."""
    readme: str = ""
    """How to import it into the program, plain text."""


def all_collections(export: Export) -> list[tuple[str, ...]]:
    """Every collection path, parents before children: the export's own
    list, then any path (or parent) that only papers and notes name."""
    paths: dict[tuple[str, ...], None] = {}
    for path in [
        *export.collections,
        *(
            path
            for item in [*export.papers, *export.notes]
            for path in item.collections
        ),
    ]:
        for depth in range(1, len(path) + 1):
            paths.setdefault(path[:depth])
    return list(paths)


def children(
    paths: list[tuple[str, ...]],
) -> dict[tuple[str, ...], list[tuple[str, ...]]]:
    """Each path's subcollections in order; ``()`` holds the top ones."""
    found: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for path in paths:
        found.setdefault(path[:-1], []).append(path)
    return found


def date_parts(date: object) -> list[int]:
    """Year, month, day of a CSL date, as far as known; [] for none or a
    date that is only text."""
    if not isinstance(date, dict):
        return []
    parts = date.get("date-parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
        return []
    found: list[int] = []
    for part in parts[0][:3]:
        try:
            found.append(int(part))
        except (TypeError, ValueError):
            break
    return found


def raw_date(date: object) -> str | None:
    """The text of a date given only as text (``Spring 2024``)."""
    if isinstance(date, dict) and not date_parts(date) and date.get("raw"):
        return str(date["raw"]).strip() or None
    return None


def iso_date(date: object, separator: str = "-") -> str | None:
    """``2024-03-02``, ``2024-03`` or ``2024``."""
    parts = date_parts(date)
    if not parts:
        return None
    return separator.join(
        [str(parts[0]).zfill(4), *(f"{part:02d}" for part in parts[1:])]
    )


def year(csl: dict[str, Any]) -> str | None:
    """The year of publication, also from a date given as text."""
    parts = date_parts(csl.get("issued"))
    if parts:
        return str(parts[0])
    found = re.search(r"\d{4}", raw_date(csl.get("issued")) or "")
    return found.group() if found else None


def first(value: object) -> str | None:
    """A field's text; of a list (CSL allows them for ISBN, …) the first."""
    if isinstance(value, list):
        value = value[0] if value else None
    text = str(value).strip() if value is not None else ""
    return text or None


def identifier(paper: ExportedPaper, scheme: Scheme) -> str | None:
    found = next((value for s, value in paper.identifiers if s == scheme), None)
    if scheme == Scheme.DOI:
        return found or first(paper.csl.get("DOI"))
    if scheme == Scheme.ISBN:
        return first(paper.csl.get("ISBN")) or found
    return found


_ARXIV_DOI = re.compile(r"10\.48550/arxiv\.(.+)", re.IGNORECASE)


def arxiv_id(paper: ExportedPaper) -> str | None:
    """The paper's arXiv ID, also from an arXiv DOI."""
    found = identifier(paper, Scheme.ARXIV)
    if found:
        return found
    doi = _ARXIV_DOI.fullmatch(identifier(paper, Scheme.DOI) or "")
    return doi.group(1) if doi else None


def family(name: dict[str, Any]) -> str:
    """The family name with its particle (``van Gogh``)."""
    return " ".join(
        str(part)
        for part in (name.get("non-dropping-particle"), name.get("family"))
        if part
    )


def given(name: dict[str, Any]) -> str:
    return " ".join(
        str(part) for part in (name.get("given"), name.get("dropping-particle")) if part
    )


def all_keywords(paper: ExportedPaper) -> list[str]:
    """The person's tags, then the paper's own keywords not among them."""
    seen: set[str] = set()
    words: list[str] = []
    for word in [*paper.tags, *paper.keywords]:
        if word.strip() and word.casefold() not in seen:
            seen.add(word.casefold())
            words.append(word.strip())
    return words


def keyword_warning(export: Export, program: str) -> list[str]:
    if not any(paper.keywords for paper in export.papers):
        return []
    return [
        f"{program} has one kind of keyword: the papers' own keywords (from "
        "their details) are written together with your tags."
    ]


def notes_warning(export: Export, where: str) -> list[str]:
    if not export.notes:
        return []
    count = len(export.notes)
    return [
        f"{count} note{'s' if count != 1 else ''} without a paper "
        f"{'are' if count != 1 else 'is'} not in the file: {where}"
    ]
