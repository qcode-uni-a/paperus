"""Citation export: CSL-JSON (for Pandoc, Zotero, citation styles) and BibTeX
(for LaTeX), from the metadata paperus keeps (CSL-JSON, see ``library``).

The BibTeX follows the conventions of Zotero's own BibTeX export, so that
people moving over get the entries, keys and title protection they know:
keys like ``gan_prizes_2026``, Zotero's field order and entry types, every
capitalised title word in braces, Unicode kept as it is. Different on
purpose: arXiv papers get ``eprint`` and ``archiveprefix`` as in arXiv's own
BibTeX (Zotero writes only a note), and no empty line opens the file. Only
the conventions are taken (Zotero's translator is AGPL), not its code.
"""

import re
import unicodedata
from collections.abc import Callable
from typing import Any

from paperus import library
from paperus.models import Item

# CSL type → BibTeX entry type, as Zotero maps the matching Zotero types;
# anything else (preprints, documents, web pages, …) is @misc.
_ENTRY_TYPES = {
    "article-journal": "article",
    "article-magazine": "article",
    "article-newspaper": "article",
    "paper-conference": "inproceedings",
    "book": "book",
    "chapter": "incollection",
    "report": "techreport",
    "thesis": "phdthesis",
    "manuscript": "unpublished",
    "patent": "patent",
}

_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()  # noqa: SIM905

# Removed from a title before its first word goes into a key (Zotero's list).
_KEY_SKIP = re.compile(
    r"\b(a|an|the|some|from|on|in|to|of|do|with|der|die|das|ein|eine|einer|"
    r"eines|einem|einen|un|une|la|le|l'|les|el|las|los|al|uno|una|unos|unas|"
    r"de|des|del|d')(\s+|\b)"
)
_KEY_CLEAN = re.compile(r"[^a-z0-9_-]")
# Hyphens and dashes in page ranges become "--".
_DASHES = re.compile("\\s*[-\u2010-\u2015\u2053]+\\s*")
_MASTERS = {"master", "masters", "master's", "ms", "msc", "ma"}


def citation_key_base(csl: dict[str, Any]) -> str:
    """The paper's own key (e.g. from Better BibTeX or Zotero), or one in
    Zotero's form ``author_titleword_year``: the first creator's family
    name, the title's first word that is not an article or preposition."""
    own = csl.get("citation-key")
    if isinstance(own, str) and own.strip():
        return own.strip()
    names = csl.get("author") or csl.get("editor") or []
    first = names[0] if names else {}
    family = " ".join(
        filter(None, [first.get("non-dropping-particle"), first.get("family")])
    ) or str(first.get("literal") or "")
    author = _plain(family).replace(" ", "_").replace(",", "") or "noauthor"
    title = _KEY_SKIP.sub("", _plain(str(csl.get("title") or ""))).split()
    word = title[0] if title else "notitle"
    year = str(_year(csl) or "nodate")
    return _KEY_CLEAN.sub("", f"{author}_{word}_{year}")


def keyed(items: list[Item]) -> list[tuple[str, dict[str, Any]]]:
    """Each item's CSL-JSON with a citation key unique in this export (equal
    generated keys get -1, -2, … in the items' order, as in Zotero)."""
    pairs = [(item, library.citation_csl(item)) for item in items]
    own = {
        str(csl["citation-key"]).strip() for _, csl in pairs if csl.get("citation-key")
    }
    seen: set[str] = set()
    result: list[tuple[str, dict[str, Any]]] = []
    for _, csl in pairs:
        base = key = citation_key_base(csl)
        if not csl.get("citation-key"):
            suffix = 0
            while key in seen or key in own:
                suffix += 1
                key = f"{base}-{suffix}"
        seen.add(key)
        result.append((key, csl))
    return result


def csl_json(items: list[Item]) -> list[dict[str, Any]]:
    """CSL-JSON for the items, ``id`` and ``citation-key`` being the key
    (what Pandoc cites by)."""
    return [{**csl, "id": key, "citation-key": key} for key, csl in keyed(items)]


def bibtex(
    items: list[Item], keywords: Callable[[Item], list[str]] | None = None
) -> str:
    """BibTeX entries in UTF-8 (fine for biber and modern bibtex);
    ``keywords`` gives a paper's tags."""
    entries = [
        _entry(key, csl, keywords(item) if keywords else [])
        for item, (key, csl) in zip(items, keyed(items), strict=True)
    ]
    return "\n\n".join(entries) + "\n" if entries else ""


def _entry(key: str, csl: dict[str, Any], tags: list[str]) -> str:
    entry = _ENTRY_TYPES.get(str(csl.get("type") or ""), "misc")
    genre = csl.get("genre")
    if entry == "phdthesis":
        kind = re.sub(r"\s|\.|thesis|unpublished", "", str(genre or "").lower())
        if kind in _MASTERS:
            entry, genre = "mastersthesis", None
    fields: list[tuple[str, str]] = []

    def add(name: str, value: object, *, raw: bool = False) -> None:
        if value is None or value == "" or value == []:
            return
        text = str(value) if raw else _escape(str(value))
        if name in ("title", "type", "shorttitle", "booktitle", "series"):
            text = _protect(text)
        fields.append((name, "{" + text + "}"))

    add("address", csl.get("publisher-place"))
    add("edition", csl.get("edition"))
    if entry in ("phdthesis", "techreport"):
        add("type", genre)
    add("series", csl.get("collection-title"))
    add("title", _first(csl.get("title")))
    add("volume", csl.get("volume"))
    add("isbn", _first(csl.get("ISBN")))
    add("issn", _first(csl.get("ISSN")))
    add("shorttitle", _first(csl.get("title-short")))
    add("url", csl.get("URL"), raw=True)
    add("doi", csl.get("DOI"), raw=True)
    add("abstract", csl.get("abstract"))
    add("language", csl.get("language"))
    add("number", csl.get("number") or csl.get("issue") or csl.get("collection-number"))
    add("urldate", _iso_date(csl.get("accessed")))
    container = _first(csl.get("container-title"))
    if entry in ("incollection", "inproceedings"):
        add("booktitle", container)
    elif entry != "book":
        add("journal", container)
    publisher = csl.get("publisher")
    if entry in ("phdthesis", "mastersthesis"):
        add("school", publisher)
    elif entry == "techreport":
        add("institution", publisher)
    else:
        add("publisher", publisher)
    for role in ("author", "editor", "translator"):
        names = csl.get(role) or []
        if names:
            fields.append((role, "{" + " and ".join(_name(n) for n in names) + "}"))
    month = _month(csl)
    if month:
        fields.append(("month", month))  # a BibTeX macro: no braces
    add("year", _year(csl))
    add("note", csl.get("note"))
    arxiv = _arxiv_id(csl)
    if arxiv:  # as arXiv's own BibTeX has it (Zotero writes only a note)
        add("eprint", arxiv)
        add("archiveprefix", "arXiv")
    add("keywords", ", ".join(tags))
    page = csl.get("page")
    add("pages", _DASHES.sub("--", str(page)) if page else None)
    body = ",\n".join(f"\t{name} = {value}" for name, value in fields)
    return f"@{entry}{{{key},\n{body},\n}}"


def _name(name: dict[str, Any]) -> str:
    if name.get("literal"):
        return "{" + _escape(str(name["literal"])) + "}"
    family = " ".join(
        filter(None, [name.get("non-dropping-particle"), name.get("family")])
    )
    given = " ".join(filter(None, [name.get("given"), name.get("dropping-particle")]))
    parts = [_escape(family)]
    if name.get("suffix"):
        parts.append(_escape(str(name["suffix"])))
    if given:
        parts.append(_escape(given))
    return ", ".join(parts).replace(" and ", " {and} ")


_ESCAPES = {
    "\\": r"{\textbackslash}",
    "|": r"{\textbar}",
    "<": r"{\textless}",
    ">": r"{\textgreater}",
    "~": r"{\textasciitilde}",
    "^": r"{\textasciicircum}",
    "{": r"\{",
    "}": r"\}",
    "#": r"\#",
    "$": r"\$",
    "%": r"\%",
    "&": r"\&",
    "_": r"\_",
}
_SPECIAL = re.compile("|".join(re.escape(c) for c in _ESCAPES))


def _escape(text: str) -> str:
    """LaTeX's special characters, as Zotero writes them; Unicode letters
    stay as they are (Zotero's default, UTF-8)."""
    return _SPECIAL.sub(lambda m: _ESCAPES[m.group()], text)


_WORD = re.compile(r"[^\W_]+")


def _protect(text: str) -> str:
    """Zotero's case protection: every word with a capital letter in braces,
    except a first word whose only capital is its initial."""

    def brace(match: re.Match[str]) -> str:
        word = match.group()
        if not any(c.isupper() for c in word):
            return word
        if match.start() == 0 and not any(c.isupper() for c in word[1:]):
            return word
        before = text[match.start() - 1] if match.start() else ""
        if before == "\\":  # a LaTeX command from the escaping
            return word
        return "{" + word + "}"

    return _WORD.sub(brace, text)


def _first(value: object) -> str | None:
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value else None


def _date_parts(date: object) -> list[Any]:
    if not isinstance(date, dict):
        return []
    parts = date.get("date-parts") or [[]]
    return list(parts[0]) if parts and parts[0] else []


def _year(csl: dict[str, Any]) -> int | str | None:
    parts = _date_parts(csl.get("issued"))
    if parts and parts[0]:
        return parts[0]
    raw = str((csl.get("issued") or {}).get("raw") or "")
    found = re.search(r"\d{4}", raw)
    return found.group() if found else None


def _month(csl: dict[str, Any]) -> str | None:
    parts = _date_parts(csl.get("issued"))
    try:
        return _MONTHS[int(parts[1]) - 1] if len(parts) > 1 else None
    except (ValueError, IndexError):
        return None


def _iso_date(date: object) -> str | None:
    parts = _date_parts(date)
    if not parts:
        return None
    return "-".join(f"{int(p):02d}" if i else str(p) for i, p in enumerate(parts))


_ARXIV_DOI = re.compile(r"10\.48550/arxiv\.(.+)", re.IGNORECASE)


def _arxiv_id(csl: dict[str, Any]) -> str | None:
    found = _ARXIV_DOI.fullmatch(str(csl.get("DOI") or ""))
    return found.group(1) if found else None


def _plain(text: str) -> str:
    """Lower case without diacritics (é → e), for keys."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))
