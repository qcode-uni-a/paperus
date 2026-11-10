"""Text extraction and chunking.

First version: text per PDF page (pypdfium2), split into chunks of about
200 words at paragraph and sentence boundaries, within a page. Structure-aware
chunking (sections, captions) with GROBID or Docling comes later.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

from paperus import pdf

TARGET_WORDS = 200
MAX_WORDS = 350
LONGEST_WORD = 200

_HYPHENATED = re.compile(r"(\w)-\n(?=[a-z])")
# How PDFium reads a word hyphenated at a line's end (LaTeX's, among
# others): its hyphen as U+0002; and soft hyphens.
_HYPHEN_MARKS = re.compile(r"[\u0002\u00ad]\n?")


def mend_hyphens(text: str) -> str:
    """Words broken at a line's end joined again (lines end in ``\\n``)."""
    return _HYPHENATED.sub(r"\1", _HYPHEN_MARKS.sub("", text))


_BLANK_LINES = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9])")


# Headings of a reference list (alone on a line, maybe numbered) and of what
# may follow it (appendices are body text again).
_REFERENCES = re.compile(
    r"^\s*(?:#+\s*)?(?:\d+\.?|[IVX]+\.)?\s*(?:references(?: and notes)?|reference list"
    r"|bibliography|literature(?: cited)?|works cited|literatur(?:verzeichnis)?"
    r"|quellen(?:verzeichnis)?)\s*:?\s*$",
    re.IGNORECASE,
)
_AFTER_REFERENCES = re.compile(
    r"^\s*(?:#+\s*)?(?:[A-Z]\.?\s+)?(?:appendix|appendices|supplementary"
    r"(?: material| information)?|supporting information|anhang)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TextChunk:
    text: str
    page: int | None
    references: bool = False
    """Part of a reference list: kept for keyword search, not embedded."""


def extract_pdf_pages(path: Path) -> list[str]:
    """The text of each page; empty strings for pages without text (read
    in a helper process, see ``paperus.pdf``)."""
    return pdf.pages(path)


_BLOCKS = [
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "figcaption", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr",
    "li", "main", "nav", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul",
]  # fmt: skip


def html_text(html: bytes) -> str:
    """The readable text of a web page (e.g. a snapshot saved by Zotero):
    without scripts, styles and markup; blocks become paragraphs."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "template", "head"]):
        tag.decompose()
    for block in soup(_BLOCKS):
        block.insert_after("\n\n")
    return soup.get_text()


def _paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = mend_hyphens(text)
    # Words longer than any real word (embedded images, minified code) only
    # bloat a passage (Postgres indexes at most 1 MB of text per passage).
    paragraphs = (
        " ".join(w for w in p.split() if len(w) <= LONGEST_WORD)
        for p in _BLANK_LINES.split(text)
    )
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


def chunk_text(
    text: str, page: int | None = None, references: bool = False
) -> list[TextChunk]:
    """Merge short paragraphs and split long ones, aiming at TARGET_WORDS."""
    chunks: list[TextChunk] = []
    current: list[str] = []
    current_words = 0
    for paragraph in _paragraphs(text):
        for piece in _split_long(paragraph):
            words = len(piece.split())
            if current and current_words + words > TARGET_WORDS:
                chunks.append(TextChunk("\n\n".join(current), page, references))
                current, current_words = [], 0
            current.append(piece)
            current_words += words
    if current:
        chunks.append(TextChunk("\n\n".join(current), page, references))
    return chunks


def _sections(
    pages: list[tuple[str, int | None]],
) -> list[tuple[str, int | None, bool]]:
    """Split pages where a reference list starts or ends: (text, page, refs)."""
    sections: list[tuple[str, int | None, bool]] = []
    in_references = False
    for text, page in pages:
        lines: list[str] = []
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            starts = not in_references and _REFERENCES.match(line)
            ends = in_references and _AFTER_REFERENCES.match(line)
            if starts or ends:
                sections.append(("\n".join(lines), page, in_references))
                lines = []
                in_references = bool(starts)
            lines.append(line)
        sections.append(("\n".join(lines), page, in_references))
    return [s for s in sections if s[0].strip()]


def chunk_document(text: str) -> list[TextChunk]:
    """A text file (Markdown, …): chunks without pages, references marked."""
    return [c for t, _, r in _sections([(text, None)]) for c in chunk_text(t, None, r)]


def chunk_pages(pages: list[str]) -> list[TextChunk]:
    """PDF pages: chunks within pages, references marked."""
    numbered: list[tuple[str, int | None]] = [(t, n) for n, t in enumerate(pages, 1)]
    return [c for t, page, r in _sections(numbered) for c in chunk_text(t, page, r)]
