"""Importing libraries from other reference managers.

Each format (``bibtex``, ``ris``, ``csljson``, later ``zotero``) is read
into one common form, an ``Export``; ``apply`` then adds it to paperus the
same way for every format. See docs/ingestion.md.
"""

from dataclasses import dataclass, field
from typing import Any

from paperus.identifiers import Scheme


@dataclass
class ExportedFile:
    path: str
    """As written in the export: relative to it, or an absolute path from
    the exporting computer (then only the file name can be matched)."""
    media_type: str | None = None
    description: str | None = None


@dataclass
class ExportedPaper:
    csl: dict[str, Any]
    identifiers: list[tuple[Scheme, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    collections: list[tuple[str, ...]] = field(default_factory=list)
    """Paths of collection names, from the top down."""
    notes: list[str] = field(default_factory=list)
    """Markdown."""
    files: list[ExportedFile] = field(default_factory=list)
    source_key: str = ""
    """The entry's key in the export, for messages."""


@dataclass
class ExportedNote:
    """A note on no paper (Zotero's standalone notes)."""

    text: str
    collections: list[tuple[str, ...]] = field(default_factory=list)


@dataclass
class Export:
    format: str
    papers: list[ExportedPaper] = field(default_factory=list)
    notes: list[ExportedNote] = field(default_factory=list)
    collections: list[tuple[str, ...]] = field(default_factory=list)
    """Every collection path, also empty ones, parents before children."""
    problems: list[str] = field(default_factory=list)
    """Entries that could not be read, for the report."""
