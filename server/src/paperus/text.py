"""Text extraction and chunking.

First version: text per PDF page (pypdfium2), split into chunks of about
200 words at paragraph and sentence boundaries, within a page. Structure-aware
chunking (sections, captions) with GROBID or Docling comes later.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pypdfium2

TARGET_WORDS = 200
MAX_WORDS = 350

_HYPHENATED = re.compile(r"(\w)-\n(?=[a-z])")
_BLANK_LINES = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9])")


@dataclass(frozen=True)
class TextChunk:
    text: str
    page: int | None


def extract_pdf_pages(path: Path) -> list[str]:
    """The text of each page; empty strings for pages without text."""
    pdf = pypdfium2.PdfDocument(path)
    try:
        pages = []
        for index in range(len(pdf)):
            page = pdf[index]
            text_page = page.get_textpage()
            pages.append(text_page.get_text_bounded())
            text_page.close()
            page.close()
        return pages
    finally:
        pdf.close()


def _paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHENATED.sub(r"\1", text)
    paragraphs = (" ".join(p.split()) for p in _BLANK_LINES.split(text))
    return [p for p in paragraphs if p]


def _split_long(paragraph: str) -> list[str]:
    """Split at sentence ends into pieces of at most MAX_WORDS."""
    pieces: list[str] = []
    current: list[str] = []
    for sentence in _SENTENCE_END.split(paragraph):
        words = sentence.split()
        if current and len(current) + len(words) > TARGET_WORDS:
            pieces.append(" ".join(current))
            current = []
        current.extend(words)
        while len(current) > MAX_WORDS:
            pieces.append(" ".join(current[:MAX_WORDS]))
            current = current[MAX_WORDS:]
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_text(text: str, page: int | None = None) -> list[TextChunk]:
    """Merge short paragraphs and split long ones, aiming at TARGET_WORDS."""
    chunks: list[TextChunk] = []
    current: list[str] = []
    current_words = 0
    for paragraph in _paragraphs(text):
        for piece in _split_long(paragraph):
            words = len(piece.split())
            if current and current_words + words > TARGET_WORDS:
                chunks.append(TextChunk("\n\n".join(current), page))
                current, current_words = [], 0
            current.append(piece)
            current_words += words
    if current:
        chunks.append(TextChunk("\n\n".join(current), page))
    return chunks


def chunk_pages(pages: list[str]) -> list[TextChunk]:
    return [
        chunk
        for number, text in enumerate(pages, 1)
        for chunk in chunk_text(text, number)
    ]
