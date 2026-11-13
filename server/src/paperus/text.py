"""Text extraction and chunking.

Passages of about 200 words, cut at paragraph and sentence boundaries. A
PDF's text comes from its page layouts (``paperus.page_layout``): its
pieces in reading order, one flow across columns and pages, without
margins, running headers and footers, and figures' labels; a passage starts
at each section heading, so a change in one part of a paper changes the
passages of its section only. A PDF without layouts: within each page.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bs4 import BeautifulSoup

from paperus import pdf

TARGET_WORDS = 200
MAX_WORDS = 350
LONGEST_WORD = 200

_HYPHENATED = re.compile(r"(\w)-\n(?=[a-z])")
# How PDFium reads a word hyphenated at a line's end (LaTeX's, among
# others): its hyphen as U+0002; and soft hyphens.
# (U+FFFE character by character).
_HYPHEN_MARKS = re.compile(r"[\u0002\u00ad\ufffe]\n?")


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


# A section's heading alone on its line: numbered ("II. MODEL", "2.1 Results
# and discussion", "A. Spin qubits"), its words without digits; or one of
# the usual unnumbered ones.
_HEADING = re.compile(
    r"^\s*(?:(?:[IVX]+\.|[A-Z]\.|\d+(?:\.\d+)*\.?)\s+[A-Z][^\d,;:=]{0,80}"
    r"|(?:abstract|introduction|conclusions?|summary|discussion|methods"
    r"|results(?: and discussion)?|acknowledge?ments?|appendix(?: [A-Z])?)\.?)\s*$",
    re.IGNORECASE,
)
_HEADING_WORDS = 10
# A heading starts a passage after at least this many words.
SECTION_WORDS = 30


def heading(line: str) -> bool:
    """Whether a line is a section's heading."""
    return bool(_HEADING.match(line)) and len(line.split()) <= _HEADING_WORDS


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


def _cut(words: list[tuple[str, int]], references: bool) -> list[TextChunk]:
    """A section's words (each with its page) in passages: sentences joined
    up to TARGET_WORDS, longer ones cut at MAX_WORDS."""
    chunks: list[TextChunk] = []
    current: list[tuple[str, int]] = []

    def close(upto: int) -> None:
        nonlocal current
        part, current = current[:upto], current[upto:]
        chunks.append(TextChunk(" ".join(w for w, _ in part), part[0][1], references))

    sentence: list[tuple[str, int]] = []
    for index, word in enumerate(words):
        sentence.append(word)
        after = words[index + 1][0] if index + 1 < len(words) else None
        if after is not None and not (
            word[0][-1] in ".!?" and _SENTENCE_START.match(after)
        ):
            continue
        if current and len(current) + len(sentence) > TARGET_WORDS:
            close(len(current))
        current += sentence
        sentence = []
        while len(current) > MAX_WORDS:
            close(MAX_WORDS)
    if current:
        close(len(current))
    return chunks


_SENTENCE_START = re.compile(r"[\"'(\[A-Z0-9]")
# A word broken at the end of a piece: a hyphen mark, or a hyphen (joined
# before a small letter, as ``mend_hyphens`` does within a piece).
_BROKEN = re.compile(r"(?:[\u0002\u00ad\ufffe]|\w-)$")


# A reference list's entries: numbered ("[12]", "12.") or with a year.
_ENTRY = re.compile(r"^\s*(?:\[\d+\]|\d+\.\s[^,]*,)|\b(?:1[89]|20)\d\d\b")
_ENTRIES_NEAR = 4


# ("1. Yoneda, J. …", not a contents' "1. Introduction")
_FIRST_ENTRY = re.compile(r"^\s*(?:\[1\]|\(1\)|1\.\s[^,]*,)")


def _references_follow(lines: list[str]) -> bool:
    """Whether the lines after a reference list's heading are its entries
    (not a table of contents' next lines): the first numbered, or years."""
    near = [line for line in lines[:_ENTRIES_NEAR] if line.strip()]
    if near and _FIRST_ENTRY.match(near[0]):
        return True
    return sum(bool(_ENTRY.search(line)) for line in near) >= 2


type Flow = Literal["text", "caption", "page"]
"""How a part of a PDF's text is read: as the flow's text; apart from it
(a caption: the flow runs on past it); or as a section of its own (a page
without layout, e.g. read by OCR)."""


def chunk_flow(parts: list[tuple[str, int, Flow]]) -> list[TextChunk]:
    """PDF pages read by their layouts: their pieces' texts, each with its
    page (from 1) and how it is read, in reading order. The text is one
    flow across columns and pages, cut into passages at sentence ends, a
    new one at each section heading and where a reference list starts or
    ends; each part apart is cut on its own. Each passage with the page it
    starts on."""
    # The flow's lines: each with its page, whether its first word is the
    # end of one broken at the end of the piece before, and whether a new
    # section starts there.
    flow: list[tuple[str, int, bool, bool]] = []
    # The parts apart, each by the line of the flow it comes before.
    apart: list[tuple[int, list[tuple[str, int]]]] = []
    broken = False
    alone = False
    for raw, page, kind in parts:
        text = mend_hyphens(raw.replace("\r\n", "\n").replace("\r", "\n").strip())
        if kind == "caption":
            words = [(w, page) for w in text.split() if len(w) <= LONGEST_WORD]
            if words:
                apart.append((len(flow), words))
            continue
        if not text:
            continue
        lines = text.split("\n")
        new = alone or kind == "page"
        flow += [
            (line, page, broken and not k and not new, new and not k)
            for k, line in enumerate(lines)
        ]
        broken = bool(_BROKEN.search(raw.rstrip()))
        alone = kind == "page"

    # Sections: their words (each with its page), whether a reference list,
    # and the line of the flow they start at.
    sections: list[tuple[list[tuple[str, int]], bool, int]] = [([], False, 0)]
    for index, (line, page, joins, new) in enumerate(flow):
        words, references, start = sections[-1]
        starts = (
            not references
            and _REFERENCES.match(line)
            and _references_follow([f[0] for f in flow[index + 1 :]])
        )
        ends = references and _AFTER_REFERENCES.match(line)
        now = bool(starts) or (references and not ends)
        # (A heading right under another, or after a few words, goes with
        # them: no passages of a title alone.)
        if words and (
            new or now != references or (heading(line) and len(words) >= SECTION_WORDS)
        ):
            sections.append(([], now, index))
        else:
            sections[-1] = (words, now, start)
        words = sections[-1][0]
        for word in line.split():
            if len(word) > LONGEST_WORD:
                continue
            if joins and words:
                # A word broken at the end of the piece before: whole again
                # (a hyphen kept before a capital: "Rabi-Bloch").
                last, at = words[-1]
                if last.endswith("-") and word[:1].islower():
                    last = last[:-1]
                words[-1] = (last + word, at)
            else:
                words.append((word, page))
            joins = False

    chunks: list[TextChunk] = []
    for k, (words, references, start) in enumerate(sections):
        end = sections[k + 1][2] if k + 1 < len(sections) else len(flow) + 1
        if words:
            chunks += _cut(words, references)
        # (A part apart goes with the line of the flow before it.)
        for _, own in (a for a in apart if start <= max(0, a[0] - 1) < end):
            chunks += _cut(own, references)
    return chunks
