"""Cover pages: a page put in front of (or behind) a paper by the site it
came from, not part of the paper: IOP's "To cite this article", JSTOR's
terms, ResearchGate's, Taylor & Francis', a repository's sheet with the
licence. Recognised when a file is read; the file stays as it is, the
pages are noted (``File.cover_pages``) and left out of its text, and the
viewer starts after them (#42).

A cover is short and says what covers say: one of the sources' own
phrases, or two of the phrases repositories share. A paper's real first
page is longer (a page of a paper with "Downloaded from …" in its footer
has thousands of characters), so a phrase alone is not enough.
"""

import re

# Longer than a cover sheet (IOP's has about 130 words, a repository's
# 70); shorter than nearly any page of a paper.
MOST_WORDS = 300

# The sources' own phrases: one is enough.
OWN = (
    "to cite this article",  # IOP, Taylor & Francis, Cambridge
    "view the article online for updates and enhancements",  # IOP
    "this content downloaded from",  # JSTOR
    "your use of the jstor archive",
    "jstor is a not-for-profit service",
    "see discussions, stats, and author profiles for this publication",  # ResearchGate
    "full terms & conditions of access and use",  # Taylor & Francis
    "cambridge core terms of use",
    "link to license to see what you are allowed to do",  # UNSWorks
    "this document is downloaded from",  # DR-NTU and others
)
# Repositories' (Pure, DSpace, ETH's Research Collection): two of them.
SHARED = (
    "downloaded from",
    "terms of use",
    "terms and conditions",
    "permanent link",
    "persistent link",
    "rights / license",
    "this version is available at",
    "citation for published version",
    "general rights",
    "take down policy",
    "copyright and moral rights",
)


def is_cover(text: str) -> bool:
    words = text.split()
    if not words or len(words) > MOST_WORDS:
        return False
    plain = re.sub(r"\s+", " ", text).lower()
    if any(phrase in plain for phrase in OWN):
        return True
    return sum(phrase in plain for phrase in SHARED) >= 2


def cover_pages(pages: list[str]) -> list[int]:
    """The cover pages among a PDF's pages (from 1): the first, and the last
    of a longer file (some repositories put theirs behind)."""
    found = []
    if len(pages) > 1 and is_cover(pages[0]):
        found.append(1)
    if len(pages) > 2 and is_cover(pages[-1]):
        found.append(len(pages))
    return found
