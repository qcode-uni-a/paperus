"""Finding out what an uploaded file is: identifiers in its text, its title.

Runs after text extraction for items whose metadata is only a placeholder
from the upload (``MetadataSource.FILE``). A DOI or arXiv ID on the first
pages (or an arXiv ID as file name) is looked up, and used only if the
registry's title also appears on those pages: papers cite other DOIs, and a
wrong match renames the paper.
Without an identifier, a plausible title embedded in the PDF is used.
"""

import logging
import re
import uuid
from pathlib import Path

import httpx2
import pypdfium2
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import library, metadata
from paperus.identifiers import (
    InvalidIdentifier,
    Scheme,
    implied_by_doi,
    normalize_arxiv,
    normalize_doi,
)
from paperus.models import Chunk, File, FileChunk, MetadataSource, TextStatus
from paperus.storage import BlobStore

log = logging.getLogger(__name__)

PDF = "application/pdf"
FIRST_PAGES = 2

_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
_ARXIV = re.compile(
    r"arXiv:\s*(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})", re.IGNORECASE
)
_WORD = re.compile(r"\w+")
_NOT_TITLES = re.compile(
    r"^(untitled|microsoft word|document\d*|title|paper|manuscript"
    r"|\S+\.(docx?|tex|pdf|dvi))",
    re.IGNORECASE,
)


def find_identifiers(text: str) -> list[tuple[Scheme, str]]:
    """DOIs and arXiv IDs in order of appearance, normalized, without repeats."""
    found: list[tuple[Scheme, str]] = []
    for match in _DOI.finditer(text):
        try:
            doi = normalize_doi(match.group().rstrip(".,;:)]}'"))
            found.append((Scheme.DOI, doi))
        except InvalidIdentifier:
            continue
    for match in _ARXIV.finditer(text):
        try:
            found.append((Scheme.ARXIV, normalize_arxiv(match.group(1))))
        except InvalidIdentifier:
            continue
    return list(dict.fromkeys(found))


# arXiv names downloads by ID ("2101.00001v2.pdf"); DOIs appear in names
# with "/" replaced, which cannot be undone reliably, so only arXiv here.
_ARXIV_FILENAME = re.compile(
    r"^(?:arxiv[_-]?)?(\d{4}\.\d{4,5})(?:v\d+)?$", re.IGNORECASE
)


def identifiers_in_filename(filename: str) -> list[tuple[Scheme, str]]:
    match = _ARXIV_FILENAME.match(Path(filename).stem)
    return [(Scheme.ARXIV, match.group(1))] if match else []


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def title_appears(title: str, text: str) -> bool:
    """Whether most words of the title appear in the text."""
    title_words = [w for w in _words(title) if len(w) > 2]
    if not title_words:
        return False
    text_words = set(_words(text))
    return sum(w in text_words for w in title_words) / len(title_words) >= 0.8


def plausible_title(title: str | None, filename: str) -> bool:
    """Embedded PDF titles are often a file name or "Microsoft Word - …"."""
    if not title:
        return False
    title = title.strip()
    stem = Path(filename).stem
    return (
        len(title) >= 10
        and len(_words(title)) >= 2
        and not _NOT_TITLES.match(title)
        and title.lower() != stem.lower()
    )


def embedded_title(path: Path) -> str | None:
    pdf = pypdfium2.PdfDocument(path)
    try:
        title = pdf.get_metadata_dict().get("Title")
    finally:
        pdf.close()
    return " ".join(title.split()) if title else None


def _first_pages_text(db: Session, file_id: uuid.UUID) -> str:
    rows = db.scalars(
        select(Chunk.text)
        .join(FileChunk, FileChunk.chunk_sha256 == Chunk.sha256)
        .where(FileChunk.file_id == file_id, FileChunk.page <= FIRST_PAGES)
        .order_by(FileChunk.position)
    )
    return "\n".join(rows)


def _doi_for(scheme: Scheme, value: str) -> str:
    return value if scheme == Scheme.DOI else f"10.48550/arxiv.{value}"


def identify(
    db: Session, blobs: BlobStore, http: httpx2.Client, file_id: uuid.UUID
) -> None:
    """Replace placeholder metadata with what the file says it is (no commit)."""
    file = db.get(File, file_id)
    if file is None or file.media_type != PDF or file.text_status != TextStatus.DONE:
        return
    version = file.version
    if version.metadata_source != MetadataSource.FILE or version.item.deleted_at:
        return

    text = _first_pages_text(db, file.id)
    candidates = find_identifiers(text) + identifiers_in_filename(file.filename)
    for scheme, value in dict.fromkeys(candidates):
        doi = _doi_for(scheme, value)
        identifiers = [(Scheme.DOI, doi), *implied_by_doi(doi)]
        try:
            csl, kind = metadata.lookup_doi(http, doi)
        except (metadata.DOINotFound, metadata.MetadataUnavailable):
            log.info("no metadata for %s found in file %s", doi, file_id)
            continue
        if not title_appears(metadata.csl_title(csl), text):
            log.info("title of %s not on the first pages of file %s", doi, file_id)
            continue
        try:
            with db.begin_nested():
                library.replace_metadata(
                    db,
                    version,
                    kind=kind,
                    csl=csl,
                    source=MetadataSource.LOOKUP,
                    identifiers=identifiers,
                )
        except library.IdentifierTaken as taken:
            # Already in the library; merging duplicates comes later.
            log.info("file %s is %s, already item %s", file_id, doi, taken.item_id)
        return

    with blobs.local_file(file.blob_sha256) as path:
        title = embedded_title(path)
    if plausible_title(title, file.filename):
        version.csl = {**version.csl, "title": title}
        library.refresh_item(version.item)
