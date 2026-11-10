"""Abstracts for papers whose details have none: from OpenAlex (by the
paper's DOI, in the request ``paperus.authors`` makes anyway) or, else, the
paragraph after an "Abstract" heading on the PDF's first pages. Kept on the
paper (``Item.abstract``), shown, exported and given to assistants as the
paper's abstract while its details have none: OpenAlex's replaces one found
before, the PDF's only fills a gap, and the details' own always win.
"""

import html
import re

from paperus.library import preferred_version
from paperus.models import Item
from paperus.text import mend_hyphens

# Shorter is a heading or a stray line; longer has run into the paper.
MIN_LENGTH = 200
MAX_LENGTH = 4000

# "Abstract", "ABSTRACT", "A B S T R A C T", "Summary", alone on a line or
# opening it ("Abstract—We …", "Abstract. We …").
_HEADING = re.compile(
    r"^[ \t]*(?:a[ \t]*b[ \t]*s[ \t]*t[ \t]*r[ \t]*a[ \t]*c[ \t]*t|summary)\b"
    r"[ \t]*[:.\-\u2014\u2013]?[ \t]*",  # also em and en dashes
    re.IGNORECASE | re.MULTILINE,
)
# Where an abstract ends: the first section, keywords, classification
# codes, the journal's small print.
_END = re.compile(
    r"^[ \t]*(?:(?:[1I]|1\.|I\.)[ \t]+)?(?:introduction|background)\b"
    r"|^[ \t]*(?:key[ \t]*words|index terms|pacs|msc|doi:|received|©|copyright)",
    re.IGNORECASE | re.MULTILINE,
)
_JATS = re.compile(r"<[^>]+>")


def own(item: Item) -> bool:
    """Whether the paper's details have an abstract of their own (or one
    set or removed by hand)."""
    if "abstract" in item.overrides:
        return True
    version = preferred_version(item)
    return bool(version and version.csl.get("abstract"))


def from_openalex(index: object) -> str | None:
    """The text OpenAlex keeps as positions of each word."""
    if not isinstance(index, dict) or not index:
        return None
    at: dict[int, str] = {}
    for word, places in index.items():
        if isinstance(places, list):
            for place in places:
                if isinstance(place, int):
                    at[place] = str(word)
    text = " ".join(at[i] for i in sorted(at))
    return text if len(text) >= MIN_LENGTH else None


def from_pages(pages: list[str]) -> str | None:
    """The paragraph after an "Abstract" heading on the first two pages."""
    text = "\n".join(pages[:2]).replace("\r", "")
    heading = _HEADING.search(text)
    if heading is None:
        return None
    rest = text[heading.end() :]
    end = _END.search(rest, MIN_LENGTH // 2)
    found = rest[: end.start() if end else MAX_LENGTH + 1]
    # Lines joined again; words broken at the line's end mended.
    found = mend_hyphens(found)
    found = " ".join(found.split())
    if not MIN_LENGTH <= len(found) <= MAX_LENGTH:
        return None
    return found


def plain(abstract: str) -> str:
    """An abstract as text: Crossref's JATS markup (``<jats:p>``) taken
    out, paragraphs kept as blank lines."""
    text = re.sub(r"</(?:jats:)?p>\s*", "\n\n", abstract)
    text = re.sub(r"<(?:jats:)?title>.*?</(?:jats:)?title>", "", text, flags=re.S)
    text = html.unescape(_JATS.sub("", text))
    paragraphs = [" ".join(p.split()) for p in text.split("\n\n")]
    return "\n\n".join(p for p in paragraphs if p)


def take(item: Item, text: str | None, *, replace: bool) -> bool:
    """Keep a found abstract if the paper's details have none; one found
    before only if ``replace`` (OpenAlex's, not the PDF's). Whether it was
    kept."""
    if not text or own(item) or (item.abstract and not replace):
        return False
    item.abstract = text
    return True
