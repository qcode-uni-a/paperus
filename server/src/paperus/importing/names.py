"""How alike two names of tags, collections or groups are, for suggesting
where an imported one goes.

- ``same``: equal but for case and surrounding space ("To read", "to read");
- ``nearly``: equal after folding case, spaces, ``-``, ``_``, accents and a
  simple English plural ("ToRead" and "to read", "Quantum_Dots" and
  "Quantum dots", "Thesis" and "Theses");
- ``similar``: one inside the other as whole words (of paths: their last
  parts), the same last part of a path ("Thesis" and "PhD/Thesis"), or
  nearly the same letters (difflib's ratio of the folded names at least
  0.85).
"""

import difflib
import re
import unicodedata
from typing import Literal

Likeness = Literal["same", "nearly", "similar"]
RANK: dict[Likeness, int] = {"same": 0, "nearly": 1, "similar": 2}
RATIO = 0.85

_JOINERS = re.compile(r"[\s\-_]+")
_WORD = re.compile(r"[^\W_]+")


def _plain(name: str) -> str:
    """Without accents, case-folded."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def fold(name: str) -> str:
    """Case, accents, spaces, ``-`` and ``_`` gone: ``"Quantum_Dots"`` →
    ``"quantumdots"``."""
    return _JOINERS.sub("", _plain(name)).strip()


def _forms(folded: str) -> set[str]:
    """The folded name and its singulars (dots → dot, boxes → box, studies
    → study, theses ↔ thesis)."""
    forms = {folded}
    if folded.endswith("ies") and len(folded) > 4:
        forms.add(folded[:-3] + "y")
    if folded.endswith("es") and len(folded) > 3:
        forms |= {folded[:-2], folded[:-2] + "is"}
    if folded.endswith("s") and not folded.endswith("ss") and len(folded) > 2:
        forms.add(folded[:-1])
    return forms


def _words(name: str) -> list[str]:
    return _WORD.findall(_plain(name))


def _inside(short: list[str], long: list[str]) -> bool:
    """``short``'s words, in order, among ``long``'s."""
    size = len(short)
    return 0 < size < len(long) and any(
        long[start : start + size] == short for start in range(len(long) - size + 1)
    )


def likeness(a: str, b: str) -> Likeness | None:
    """How alike two names (or paths of names, ``/`` between) are."""
    if a.strip().casefold() == b.strip().casefold():
        return "same"
    folded_a, folded_b = fold(a), fold(b)
    if folded_a and _forms(folded_a) & _forms(folded_b):
        return "nearly"
    last_a, last_b = a.rsplit("/", 1)[-1], b.rsplit("/", 1)[-1]
    if ("/" in a or "/" in b) and _forms(fold(last_a)) & _forms(fold(last_b)):
        return "similar"
    words_a, words_b = _words(last_a), _words(last_b)
    if _inside(words_a, words_b) or _inside(words_b, words_a):
        return "similar"
    ratio = difflib.SequenceMatcher(None, folded_a, folded_b).ratio()
    return "similar" if ratio >= RATIO else None


def score(a: str, b: str) -> tuple[int, float] | None:
    """For sorting suggestions, best first (lower is better)."""
    found = likeness(a, b)
    if found is None:
        return None
    ratio = difflib.SequenceMatcher(None, fold(a), fold(b)).ratio()
    return RANK[found], -ratio
