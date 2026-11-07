"""LaTeX reference lists (``.bbl`` files, ``thebibliography``) into the common
form: one paper per ``\\bibitem`` or BibLaTeX ``\\entry``.

Three kinds are read: BibLaTeX's (biber) ``.bbl`` with its fields; REVTeX and
other natbib styles that mark fields with ``\\bibinfo``; and plain styles
(plain, unsrt, abbrv, ieeetr, amsplain, …), which are free text: only
DOIs, arXiv IDs and links are found in them, and the text is kept for
finding the reference online (``paperus.importing.references``).
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import islice
from typing import Any
from urllib.parse import unquote

from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedPaper
from paperus.importing.bibtex import _TYPES, plain
from paperus.importing.common import date_parts, identifiers_of

# Real references are a few hundred characters (BibLaTeX's with an abstract a
# few thousand); longer ones are cut, as deeply nested braces take long.
MAX_REFERENCE = 10_000
# Far more than the longest reviews cite (a few thousand).
MAX_REFERENCES = 10_000


@dataclass
class Reference(ExportedPaper):
    text: str = ""
    """The reference as printed, without LaTeX: for finding it online."""
    style: str = "plain"
    """biblatex, revtex (``\\bibinfo`` fields) or plain (free text)."""

    @property
    def has_title(self) -> bool:
        title = self.csl.get("title")
        return isinstance(title, str) and bool(title) and title != "(untitled)"


def read(text: str) -> Export:
    export = Export(format="bbl")
    found = references(text)
    if len(found) > MAX_REFERENCES:
        export.problems.append(f"Only the first {MAX_REFERENCES} references were read.")
    export.papers.extend(found[:MAX_REFERENCES])
    if not export.papers:
        export.problems.append("No references (\\bibitem or \\entry) were found.")
    return export


def references(text: str) -> list[Reference]:
    """The references in the text (one more than ``MAX_REFERENCES`` at
    most): BibLaTeX entries, else the items of ``thebibliography`` (several
    lists, e.g. of several .bbl files, too)."""
    if re.search(r"\\entry\s*\{", text) and "\\endentry" in text:
        found = _biblatex(text)
    else:
        parts = re.findall(
            r"\\begin\s*\{thebibliography\}(.*?)(?:\\end\s*\{thebibliography\}|$)",
            _without_comments(text),
            flags=re.S,
        )
        found = (reference for part in parts for reference in _bibitems(part))
    return list(islice(found, MAX_REFERENCES + 1))


def style_of(found: list[Reference]) -> str:
    """The style most references are in (for messages and checks)."""
    styles = [r.style for r in found]
    return max(set(styles), key=styles.count) if styles else "none"


# --- LaTeX helpers -----------------------------------------------------------


# Braces, and escaped characters (``\{`` is no brace) to step over.
_BRACE = re.compile(r"\\.|[{}]", re.S)


def _without_comments(text: str) -> str:
    """TeX drops a comment with its line end and the next line's indent;
    BibTeX breaks long words (URLs, DOIs) that way. ``%2F`` is taken for a
    URL's encoding (hyperref's ``\\href`` reads it so)."""
    return re.sub(r"(?<!\\)%(?![0-9A-Fa-f]{2})[^\n]*(?:\n[ \t]*)?", "", text)


def _group(text: str, start: int) -> tuple[str, int] | None:
    """The braced group at ``start`` (after spaces): its content and where it
    ends; an unclosed group runs to the end."""
    i = start
    while i < len(text) and text[i] in " \t\n":
        i += 1
    if i >= len(text) or text[i] != "{":
        return None
    depth = 0
    for token in _BRACE.finditer(text, i):
        if token.group() == "{":
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1 : token.start()], token.end()
    return text[i + 1 :], len(text)


def _optional(text: str, start: int) -> int:
    """Past an optional ``[…]`` argument at ``start`` (after spaces), braces
    inside it kept together."""
    i = start
    while i < len(text) and text[i] in " \t\n":
        i += 1
    if i >= len(text) or text[i] != "[":
        return start
    depth = 0
    for j in range(i + 1, len(text)):
        char = text[j]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "]" and depth <= 0:
            return j + 1
    return len(text)


def _groups(text: str, start: int, count: int) -> tuple[list[str], int] | None:
    """``count`` braced groups one after the other."""
    found = []
    position = start
    for _ in range(count):
        group = _group(text, position)
        if group is None:
            return None
        found.append(group[0])
        position = group[1]
    return found, position


def _macro(name: str) -> re.Pattern[str]:
    # Letters and @ (the .bbl is read with \makeatletter): \href is not \href@noop.
    return re.compile(rf"\\{re.escape(name)}(?![A-Za-z@])")


def _replace(
    text: str,
    name: str,
    count: int,
    render: Callable[..., str],
    *,
    optional: bool = False,
) -> str:
    """Every ``\\name{a}{b}…`` replaced by ``render(a, b, …)``; arguments may
    hold the same macro again."""
    pattern = _macro(name)
    position = 0
    while found := pattern.search(text, position):
        after = _optional(text, found.end()) if optional else found.end()
        args = _groups(text, after, count)
        if args is None:
            position = found.end()
            continue
        values, end = args
        text = text[: found.start()] + render(*values) + text[end:]
        position = found.start()
    return text


_DROPPED = re.compile(
    r"\\(?:BibitemOpen|bibitemStop|bibitemNoStop|EOS|newblock|relax|urlprefix"
    r"|penalty\s*-?\d+|natexlab\s*\{[^{}]*\}|BibitemShut\s*\{[^{}]*\}"
    r"|selectlanguage\s*\{[^{}]*\})(?![A-Za-z@])"
)
_SEPARATORS = {
    "bibrangedash": "-",
    "bibrangessep": ", ",
    "bibinitperiod": ".",
    "bibinitdelim": " ",
    "bibinithyphendelim": "-",
    "bibnamedelima": " ",
    "bibnamedelimb": " ",
    "bibnamedelimc": " ",
    "bibnamedelimd": " ",
    "bibnamedelimi": " ",
    "bibdatedash": "-",
}


def _expand(text: str) -> str:
    """The text a reference prints, still LaTeX: field markers and links
    replaced by what they show."""
    text = re.sub(r"\\doibase(?![A-Za-z@])\s*", "https://doi.org/", text)
    for name, value in _SEPARATORS.items():
        text = re.sub(rf"\\{name}(?![A-Za-z@])\s?", value, text)
    for name in ("bibinfo", "bibfield"):
        text = _replace(text, name, 2, lambda _, value: value)
    for name in ("citenamefont", "bibnamefont", "bibfnamefont", "enquote"):
        text = _replace(text, name, 1, lambda value: value)
    text = _replace(text, "href@noop", 2, lambda _, shown: shown)
    for name in ("href", "Eprint"):
        text = _replace(text, name, 2, lambda _, shown: shown)
    text = _replace(text, "url", 1, lambda url: url)
    text = _replace(text, "doi", 1, lambda doi: f"doi:{doi}")
    text = _replace(text, "eprint", 1, lambda paper: f"arXiv:{paper}", optional=True)
    text = _replace(text, "translation", 1, lambda value: f"[{value}]")
    text = text.replace("\\newblock", " ")
    return _DROPPED.sub(" ", text)


def _plain(text: str) -> str:
    """LaTeX to text, as BibTeX values are read."""
    return plain(_expand(text)).strip(" ,;")


# --- identifiers ---------------------------------------------------------------

_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>{}]+", re.IGNORECASE)
_ARXIV_PREFIXED = re.compile(
    r"arxiv(?:\s*:\s*|\s+|\.org/(?:abs|pdf)/)"
    r"(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Za-z]{2})?/\d{7})",
    re.IGNORECASE,
)
# Old arXiv IDs carry their archive's name; only these count (not any "a/1234567").
_ARXIV_OLD = re.compile(
    r"\b((?:astro-ph|cond-mat|gr-qc|hep-ex|hep-lat|hep-ph|hep-th|math-ph|nlin"
    r"|nucl-ex|nucl-th|physics|quant-ph|math|cs|q-bio|chao-dyn|solv-int"
    r"|patt-sol|adap-org|comp-gas|chem-ph|alg-geom|dg-ga|funct-an|q-alg"
    r"|mtrl-th|supr-con|acc-phys|ao-sci|atom-ph|bayes-an|plasm-ph)"
    r"(?:\.[A-Za-z]{2})?/\d{7})(?:v\d+)?\b"
)
_ARXIV_NEW = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")


def _links(text: str) -> list[str]:
    """Targets of ``\\url``, ``\\href``, ``\\doi``, ``\\Eprint`` and
    ``\\eprint``, with LaTeX escapes and URL encoding undone."""
    found: list[str] = []
    for name, prefix in (
        ("url", ""),
        ("href", ""),
        ("Eprint", ""),
        ("doi", "doi:"),
        ("eprint", "arXiv:"),
    ):
        pattern = _macro(name)
        for match in pattern.finditer(text):
            start = _optional(text, match.end()) if name == "eprint" else match.end()
            group = _group(text, start)
            if group:
                value = re.sub(r"\\doibase\s*", "https://doi.org/", group[0])
                value = re.sub(r"\\([_%#&$~])", r"\1", value).replace("~", "")
                found.append(prefix + unquote(value.strip()))
    return found


def _find_identifiers(
    links: list[str], text: str, *, doi: str | None = None, arxiv: str | None = None
) -> tuple[str | None, str | None]:
    """The first DOI and arXiv ID: given ones first, then links, then the text."""
    searched = " ".join(links) + " " + text
    if doi is None:
        for match in _DOI.finditer(searched):
            doi = match.group().rstrip(".,;:)]}'")
            break
    if arxiv is None:
        for link in links:
            # \eprint{2101.00001}: the bare number.
            bare = link.removeprefix("arXiv:")
            if _ARXIV_NEW.match(bare):
                arxiv = bare
                break
    if arxiv is None:
        match = _ARXIV_PREFIXED.search(searched) or _ARXIV_OLD.search(searched)
        if match:
            arxiv = match.group(1)
    return doi, arxiv


def _url(links: list[str]) -> str | None:
    """A link that is not a DOI's or arXiv's (those become identifiers)."""
    for link in links:
        if re.match(r"https?://", link) and not re.search(
            r"doi\.org/|arxiv\.org/", link, re.IGNORECASE
        ):
            return link
    return None


def _paper(
    key: str,
    csl: dict[str, Any],
    text: str,
    style: str,
    *,
    doi: str | None,
    arxiv: str | None,
    book: bool = False,
    isbn: str | None = None,
) -> Reference:
    csl = {k: v for k, v in csl.items() if v}
    identifiers = identifiers_of(doi=doi, arxiv=arxiv, isbn=isbn, book=book)
    found_doi = next((v for s, v in identifiers if s == Scheme.DOI), None)
    if found_doi:
        csl["DOI"] = found_doi
    if "type" not in csl:
        csl["type"] = (
            "article-journal"
            if csl.get("container-title")
            else "article"
            if any(s == Scheme.ARXIV for s, _ in identifiers)
            else "document"
        )
    csl["citation-key"] = key
    if "page" in csl:
        csl["page"] = re.sub(r"\s*[-\u2013\u2014]+\s*", "-", csl["page"])
    return Reference(
        csl=csl,
        identifiers=identifiers,
        source_key=key,
        text=text,
        style=style,
    )


# --- thebibliography (REVTeX, natbib, plain styles) ---------------------------

_BIBITEM = re.compile(r"\\bibitem(?![A-Za-z@])")
# REVTeX puts the paper's footnotes in its reference list as Note1, Note2, ….
_FOOTNOTE = re.compile(r"^Note\d+$")


def _bibitems(text: str) -> Iterator[Reference]:
    starts = list(_BIBITEM.finditer(text))
    for n, match in enumerate(starts):
        end = starts[n + 1].start() if n + 1 < len(starts) else len(text)
        item = text[match.end() : end][:MAX_REFERENCE]
        group = _group(item, _optional(item, 0))
        if group is None:
            continue
        key, body = group[0].strip(), item[group[1] :]
        if _FOOTNOTE.match(key):
            continue
        yield _revtex(key, body) if "\\bibinfo" in body else _free_text(key, body)


def _bibinfo(body: str) -> dict[str, list[str]]:
    """``\\bibinfo{name}{value}`` fields, raw; a name may repeat (authors)."""
    fields: dict[str, list[str]] = {}
    for match in _macro("bibinfo").finditer(body):
        parts = _groups(body, match.end(), 2)
        if parts:
            name, value = parts[0]
            fields.setdefault(name.strip().lower(), []).append(value)
    return fields


def _revtex_name(value: str) -> dict[str, str]:
    family = (
        _group(value, m.end()) if (m := _macro("bibnamefont").search(value)) else None
    )
    given = (
        _group(value, m.end()) if (m := _macro("bibfnamefont").search(value)) else None
    )
    if family is None or (given is None and family[0].lstrip().startswith("{")):
        # No name parts, or one in braces: a collaboration's name.
        return {"literal": _plain(value)}
    name = {"family": _plain(family[0])}
    if given:
        name["given"] = _plain(given[0])
    return name


def _revtex(key: str, body: str) -> Reference:
    fields = _bibinfo(body)

    def get(*names: str) -> str | None:
        for name in names:
            for value in fields.get(name, []):
                if text := _plain(value):
                    return text
        return None

    csl: dict[str, Any] = {
        "title": get("title"),
        "author": [_revtex_name(v) for v in fields.get("author", [])],
        "editor": [_revtex_name(v) for v in fields.get("editor", [])],
        "container-title": get("journal", "booktitle"),
        "volume": get("volume"),
        "issue": get("number"),
        "page": get("pages"),
        "publisher": get("publisher", "school", "institution", "organization"),
        "publisher-place": get("address"),
        "edition": get("edition"),
        "collection-title": get("series"),
        "note": get("note"),
        "issued": date_parts(year=get("year")),
    }
    if get("booktitle"):
        csl["type"] = "paper-conference" if get("title") else "book"
    elif not get("journal") and get("publisher"):
        csl["type"] = "book"
    links = _links(body)
    text = _plain(body)
    doi, arxiv = _find_identifiers(links, text, doi=get("doi"), arxiv=get("eprint"))
    csl["URL"] = get("url") or _url(links)
    return _paper(
        key,
        csl,
        text,
        "revtex",
        doi=doi,
        arxiv=arxiv,
        book=csl.get("type") == "book",
        isbn=get("isbn"),
    )


def _free_text(key: str, body: str) -> Reference:
    links = _links(body)
    text = _plain(body)
    doi, arxiv = _find_identifiers(links, text)
    csl: dict[str, Any] = {"URL": _url(links)}
    title, authors = _guess_title(body)
    if title:
        csl["title"] = title
    if authors:
        csl["author"] = authors
    return _paper(key, csl, text, "plain", doi=doi, arxiv=arxiv)


def _guess_title(body: str) -> tuple[str | None, list[dict[str, str]]]:
    """A title (and the authors before it) from a plain style's layout:
    ieeetr's ``\\`\\`title,''``, the block after the authors in styles with
    ``\\newblock`` (plain, unsrt, abbrv, alpha), amsplain's ``\\emph{title}``.
    Best effort: used only when nothing better is found."""
    quoted = re.search(r"``(.+?),?''", body, flags=re.S)
    if quoted:
        return _plain(quoted.group(1)).rstrip(",. ") or None, []
    blocks = [b for b in re.split(r"\\newblock(?![A-Za-z@])", body) if b.strip()]
    if len(blocks) >= 2:
        authors = [
            {"literal": name}
            for part in re.split(r",\s*and\s+|\s+and\s+|,\s*", _plain(blocks[0]))
            if (name := part.strip(" .")) and name.lower() not in ("et al", "others")
        ]
        return _plain(blocks[1]).rstrip(",. ") or None, authors
    for name in ("emph", "textit"):
        found = _macro(name).search(body)
        if found and (group := _group(body, found.end())):
            return _plain(group[0]).rstrip(",. ") or None, []
    return None, []


# --- BibLaTeX ------------------------------------------------------------------

# \entry{key}{type}{options}, in newer biber versions with a fourth {}.
_ENTRY = re.compile(
    r"\\entry\s*\{([^{}]*)\}\s*\{([^{}]*)\}\s*\{[^{}]*\}(?:\s*\{[^{}]*\})?(.*?)"
    r"\\endentry",
    re.S,
)
_VERB = re.compile(r"\\(l?)verb\s*\{(\w+)\}(.*?)\\endl?verb", re.S)


def _biblatex(text: str) -> Iterator[Reference]:
    seen: set[str] = set()
    for match in _ENTRY.finditer(text):
        key, entry_type, body = match.group(1).strip(), match.group(2), match.group(3)
        # Entries repeat in a second sorting list or another refsection.
        if key in seen or entry_type.lower() in ("set", "xdata"):
            continue
        seen.add(key)
        yield _entry(key, entry_type.strip().lower(), body[:MAX_REFERENCE])


def _entry(key: str, entry_type: str, body: str) -> Reference:
    # Verbatim fields first: they may hold % and other characters raw.
    verbs: dict[str, str] = {}
    for match in _VERB.finditer(body):
        lines = re.findall(r"\\l?verb (.*)", match.group(3))
        verbs[match.group(2).lower()] = "".join(line.strip() for line in lines)
    body = _without_comments(_VERB.sub("", body))
    fields: dict[str, str] = {}
    for match in _macro("field").finditer(body):
        parts = _groups(body, match.end(), 2)
        if parts:
            fields[parts[0][0].strip().lower()] = parts[0][1]
    lists: dict[str, list[str]] = {}
    names: dict[str, list[dict[str, str]]] = {}
    for match in _macro("list").finditer(body):
        parts = _groups(body, match.end(), 3)
        if parts:
            lists[parts[0][0].strip().lower()] = _items(parts[0][2])
    for match in _macro("name").finditer(body):
        parts = _groups(body, match.end(), 4)
        if parts:
            names[parts[0][0].strip().lower()] = [
                _biblatex_name(item) for item in _items(parts[0][3], raw=True)
            ]

    def get(*wanted: str) -> str | None:
        for name in wanted:
            if fields.get(name) and (value := _plain(fields[name])):
                return value
        return None

    def joined(main: str, sub: str) -> str | None:
        first, second = get(main), get(sub)
        return f"{first}: {second}" if first and second else first

    csl_type = _TYPES.get(entry_type, "document")
    arxiv = (
        verbs.get("eprint") if (get("eprinttype") or "").lower() == "arxiv" else None
    )
    if entry_type == "misc" and arxiv:
        csl_type = "article"
    month = get("month")
    csl: dict[str, Any] = {
        "type": csl_type,
        "title": joined("title", "subtitle"),
        "author": names.get("author", []),
        "editor": names.get("editor", []),
        "translator": names.get("translator", []),
        "container-title": joined("journaltitle", "journalsubtitle")
        or get("journal", "booktitle", "maintitle"),
        "volume": get("volume"),
        "issue": get("number", "issue")
        if csl_type == "article-journal"
        else get("issue"),
        "number": None if csl_type == "article-journal" else get("number"),
        "page": get("pages"),
        "publisher": _first(lists, "publisher", "institution", "organization"),
        "publisher-place": _first(lists, "location", "address"),
        "edition": get("edition"),
        "collection-title": get("series"),
        "abstract": get("abstract"),
        "language": _first(lists, "language") or get("langid"),
        "ISSN": get("issn"),
        "ISBN": get("isbn"),
        "note": get("note", "addendum"),
        "genre": get("type"),
        "URL": verbs.get("url"),
        "issued": date_parts(
            year=get("year"), month=int(month) if month and month.isdecimal() else None
        ),
    }
    authors = ", ".join(p.get("family") or p.get("literal", "") for p in csl["author"])
    text = ". ".join(
        str(part)
        for part in (
            authors,
            csl["title"],
            csl["container-title"],
            csl["volume"],
            csl["page"],
            get("year"),
        )
        if part
    )
    return _paper(
        key,
        csl,
        text,
        "biblatex",
        doi=verbs.get("doi"),
        arxiv=arxiv,
        book=csl_type == "book",
        isbn=csl["ISBN"],
    )


def _items(text: str, *, raw: bool = False) -> list[str]:
    """The braced items of a ``\\list`` or ``\\name`` (``{a}{b}…``)."""
    found = []
    position = 0
    while group := _group(text, position):
        found.append(group[0])
        position = group[1]
    return found if raw else [value for item in found if (value := _plain(item))]


def _first(lists: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        if lists.get(name):
            return "; ".join(lists[name])
    return None


def _biblatex_name(item: str) -> dict[str, str]:
    """A name in biber's layout: ``{options}{family={…}, given={…}, …}``
    (biblatex 3.3 on), or ``{options}{family}{f.}{given}{g.}{prefix}{p.}
    {suffix}{s.}`` before."""
    parts = _items(item, raw=True) if item.lstrip().startswith("{") else [item]
    if len(parts) == 2 and re.search(r"\bfamily\s*=", parts[1]):
        values: dict[str, str] = {}
        for match in re.finditer(r"(\w+)\s*=\s*", parts[1]):
            group = _group(parts[1], match.end())
            if group:
                values[match.group(1)] = _plain(group[0])
        family, given = values.get("family", ""), values.get("given", "")
        prefix, suffix = values.get("prefix", ""), values.get("suffix", "")
        if not given and re.search(r"\bfamily\s*=\s*\{\s*\{", parts[1]):
            return {"literal": family}  # in braces: an organisation's name
    elif len(parts) >= 4:
        positional = [_plain(part) for part in parts[1:]] + [""] * 8
        family, given, prefix, suffix = (
            positional[0],
            positional[2],
            positional[4],
            positional[6],
        )
    else:
        return {"literal": _plain(parts[-1])}
    name = {"family": family}
    if given:
        name["given"] = given
    if prefix:
        name["non-dropping-particle"] = prefix
    if suffix:
        name["suffix"] = suffix
    return name


# --- the paper around them -----------------------------------------------------

_CITE = re.compile(r"\\[A-Za-z]*cite[A-Za-z]*\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^{}]*)\}")


def tex_title(text: str) -> str | None:
    """The ``\\title{…}`` of a LaTeX document, as text (without ``\\thanks``
    and line breaks)."""
    text = _without_comments(text)
    found = _macro("title").search(text)
    group = _group(text, _optional(text, found.end())) if found else None
    if group is None:
        return None
    title = group[0]
    for name in ("thanks", "footnote", "label"):
        title = _replace(title, name, 1, lambda _: "", optional=True)
    title = plain(re.sub(r"\\\\(?:\[[^\]]*\])?|\\newline(?![A-Za-z@])", " ", title))
    return title[:300] or None


def cited_keys(text: str) -> set[str] | None:
    """The keys a LaTeX document cites (lowercased: BibTeX ignores case), or
    None if it cites everything (``\\nocite{*}``) or nothing is found."""
    keys = {
        key.strip().lower()
        for found in _CITE.finditer(_without_comments(text))
        for key in found.group(1).split(",")
        if key.strip()
    }
    return None if not keys or "*" in keys else keys
