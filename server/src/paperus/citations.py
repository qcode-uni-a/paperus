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
ENTRY_TYPES = {
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
DASHES = re.compile("\\s*[-\u2010-\u2015\u2053]+\\s*")
MASTERS = {"master", "masters", "master's", "ms", "msc", "ma"}


def citation_key_base(csl: dict[str, Any]) -> str:
    """The paper's own key (e.g. from Better BibTeX or Zotero), or one in
    Zotero's form ``author_titleword_year``: the first creator's family
    name, the title's first word that is not an article or preposition."""
    own = own_key(csl)
    if own:
        return own
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
    """Each item's CSL-JSON (tidied, see ``_tidy``) with a citation key
    unique in this export: equal keys get -1, -2, … in the items' order, as
    in Zotero; a paper's own key wins over a generated one of the same name
    (e.g. the same .bib imported into a private and a group library)."""
    pairs = [(item, tidy(library.citation_csl(item))) for item in items]
    own = {key for _, csl in pairs if (key := own_key(csl))}
    seen: set[str] = set()
    result: list[tuple[str, dict[str, Any]]] = []
    for _, csl in pairs:
        base = key = citation_key_base(csl)
        suffix = 0
        while key in seen or (key in own and own_key(csl) != key):
            suffix += 1
            key = f"{base}-{suffix}"
        seen.add(key)
        result.append((key, csl))
    return result


# Characters BibTeX and biber do not take in keys.
_KEY_UNSAFE = re.compile(r"""[\s,{}()"#%'=\\~]""")


def own_key(csl: dict[str, Any]) -> str | None:
    """The paper's own citation key, without characters a .bib cannot hold."""
    own = csl.get("citation-key")
    if not isinstance(own, str):
        return None
    return _KEY_UNSAFE.sub("", own) or None


def tidy(csl: dict[str, Any]) -> dict[str, Any]:
    """CSL-JSON as the export expects it: name lists of objects, dates as
    objects. Imports and manual edits can hold other shapes (a year as text,
    an author as one string); they become their nearest CSL form."""
    csl = dict(csl)
    for role in ("author", "editor", "translator"):
        names = csl.get(role)
        if names is None:
            continue
        if not isinstance(names, list):
            names = [names]
        csl[role] = [
            name if isinstance(name, dict) else {"literal": str(name)}
            for name in names
            if isinstance(name, dict) or (isinstance(name, str | int) and str(name))
        ]
    for field in ("issued", "accessed"):
        date = csl.get(field)
        if date is None or isinstance(date, dict):
            continue
        csl[field] = {"raw": str(date)}
    return csl


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
    entry = ENTRY_TYPES.get(str(csl.get("type") or ""), "misc")
    genre = csl.get("genre")
    if entry == "phdthesis":
        kind = re.sub(r"\s|\.|thesis|unpublished", "", str(genre or "").lower())
        if kind in MASTERS:
            entry, genre = "mastersthesis", None
    fields: list[tuple[str, str]] = []

    def add(name: str, value: object, *, raw: bool = False) -> None:
        if value is None or value == "" or value == []:
            return
        # URLs and DOIs stay as they are, but a stray brace would end the
        # field early: those are percent-encoded.
        text = (
            str(value).replace("{", "%7B").replace("}", "%7D")
            if raw
            else escape(str(value))
        )
        if name in ("title", "type", "shorttitle", "booktitle", "series"):
            text = protect(text)
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
            fields.append(
                (role, "{" + " and ".join(bibtex_name(n) for n in names) + "}")
            )
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
    add("pages", DASHES.sub("--", str(page)) if page else None)
    body = ",\n".join(f"\t{name} = {value}" for name, value in fields)
    return f"@{entry}{{{key},\n{body},\n}}"


def bibtex_name(name: dict[str, Any]) -> str:
    """``Family, Given`` (``Family, Jr., Given``); one-part names in braces."""
    if name.get("literal"):
        return "{" + escape(str(name["literal"])) + "}"
    if not name.get("family"):  # e.g. "Plato": one name, kept whole
        whole = " ".join(str(v) for v in (name.get("given"), name.get("suffix")) if v)
        return "{" + escape(whole or "Anonymous") + "}"
    family = " ".join(
        filter(None, [name.get("non-dropping-particle"), name.get("family")])
    )
    given = " ".join(filter(None, [name.get("given"), name.get("dropping-particle")]))
    parts = [escape(family)]
    if name.get("suffix"):
        parts.append(escape(str(name["suffix"])))
    if given:
        parts.append(escape(given))
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


def escape(text: str) -> str:
    """LaTeX's special characters, as Zotero writes them; Unicode letters
    stay as they are (Zotero's default, UTF-8). A brace without its pair is
    ``{\\textbraceleft}`` or ``{\\textbraceright}``: BibTeX counts ``\\{``
    too, and the field would not end."""
    escaped = _SPECIAL.sub(lambda m: _ESCAPES[m.group()], text)
    if not balanced(text):
        escaped = escaped.replace("\\{", "{\\textbraceleft}").replace(
            "\\}", "{\\textbraceright}"
        )
    return escaped


def balanced(text: str) -> bool:
    """Whether every brace has its pair, in order."""
    depth = 0
    for char in text:
        depth += {"{": 1, "}": -1}.get(char, 0)
        if depth < 0:
            return False
    return depth == 0


_WORD = re.compile(r"[^\W_]+")


def protect(text: str) -> str:
    """Zotero's case protection: every word with a capital letter in braces,
    except a first word whose only capital is its initial."""

    def brace(match: re.Match[str]) -> str:
        word = match.group()
        if not any(c.isupper() for c in word):
            return word
        if match.start() == 0 and not any(c.isupper() for c in word[1:]):
            return word
        # (The escaping's LaTeX commands, \textbar and others, are lower case.)
        return "{" + word + "}"

    return _WORD.sub(brace, text)


def _first(value: object) -> str | None:
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value else None


def _date_parts(date: object) -> list[Any]:
    if not isinstance(date, dict):
        return []
    parts = date.get("date-parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
        return []
    return list(parts[0])


def year_of(csl: dict[str, Any]) -> int | str | None:
    """The year of publication, from the date or a raw date text."""
    return _year(csl)


def _year(csl: dict[str, Any]) -> int | str | None:
    parts = _date_parts(csl.get("issued"))
    if parts and parts[0]:
        return parts[0]
    issued = csl.get("issued")
    raw = str(issued.get("raw") or "") if isinstance(issued, dict) else ""
    found = re.search(r"\d{4}", raw)
    return found.group() if found else None


def _month(csl: dict[str, Any]) -> str | None:
    parts = _date_parts(csl.get("issued"))
    try:
        month = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return None
    return _MONTHS[month - 1] if 1 <= month <= 12 else None


def _iso_date(date: object) -> str | None:
    parts = _date_parts(date)
    try:
        return "-".join(
            f"{int(p):02d}" if i else str(int(p)) for i, p in enumerate(parts)
        )
    except (TypeError, ValueError):
        return None


_ARXIV_DOI = re.compile(r"10\.48550/arxiv\.(.+)", re.IGNORECASE)


def _arxiv_id(csl: dict[str, Any]) -> str | None:
    found = _ARXIV_DOI.fullmatch(str(csl.get("DOI") or ""))
    return found.group(1) if found else None


def _plain(text: str) -> str:
    """Lower case without diacritics (é → e), for keys."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))
