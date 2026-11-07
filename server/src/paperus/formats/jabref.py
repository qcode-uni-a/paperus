"""JabRef: a BibTeX library (``.bib``) as JabRef 5 saves one.

Entries as JabRef writes them: ``@Article{key,``, field names padded to
the longest, the entry type's required fields first, then its optional
ones, then the rest, each part in alphabetical order. Keys are the papers'
own citation keys, or ``AuthorYear`` (JabRef's default pattern) with a, b,
… for repeats. Text is LaTeX-escaped as in paperus' BibTeX export (title
words with capitals in braces, Unicode kept); ``$…$`` math stays as it is.

Collections become static groups: the tree in
``@Comment{jabref-meta: grouping: …}`` and each entry's ``groups`` field.
JabRef finds an entry's groups by name only, so a name used twice (in
different branches) gets its parent's name added, and commas or
semicolons (the field's separators) become spaces. Tags and the papers'
own keywords both go into ``keywords`` (JabRef has one kind), tags first.
Notes go into ``comment`` (Markdown, which JabRef shows as such), several
notes one after the other. Files are linked in ``file`` as
``description:path:type``, with ``\\``, ``:`` and ``;`` escaped by a
backslash; the paths are relative to the .bib, as JabRef looks for them.
Notes without a paper cannot be in a .bib.
"""

import re
import unicodedata
from typing import Any

from paperus import citations
from paperus.formats.common import (
    Written,
    all_collections,
    all_keywords,
    arxiv_id,
    children,
    date_parts,
    family,
    first,
    identifier,
    iso_date,
    keyword_warning,
    notes_warning,
    year,
)
from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedFile, ExportedPaper

README = """\
JabRef
======

paperus.bib is a JabRef library: your papers with their details, tags and
keywords, notes (in the Comments field), the PDFs (linked from the files
folder) and your collections (as groups).

1. Unpack the whole archive into one folder and keep paperus.bib and the
   files folder side by side: the files are linked relative to the .bib.
2. In JabRef: File → Open library… and choose paperus.bib. The groups are
   in the Groups pane on the left; File → Save keeps the library.
   To add the papers to a library you already have instead, open that one
   and use File → Import → Import into current library… (about this name
   in JabRef 5 and 6).
"""

# Entry types as JabRef shows them; others get a capital first letter.
_DISPLAY = {
    "article": "Article",
    "book": "Book",
    "inbook": "InBook",
    "incollection": "InCollection",
    "inproceedings": "InProceedings",
    "mastersthesis": "MastersThesis",
    "misc": "Misc",
    "phdthesis": "PhdThesis",
    "techreport": "TechReport",
    "unpublished": "Unpublished",
}
# JabRef's BibTeX types: required fields, then optional ones; each part is
# written in alphabetical order, then the other fields.
_THESIS = ({"author", "title", "school", "year"}, {"type", "address", "month", "note"})
_FIELD_ORDER: dict[str, tuple[set[str], set[str]]] = {
    "article": (
        {"author", "title", "journal", "year"},
        {"volume", "number", "pages", "month", "issn", "note"},
    ),
    "book": (
        {"author", "editor", "title", "publisher", "year"},
        {"volume", "number", "series", "address", "edition", "month", "isbn", "note"},
    ),
    "incollection": (
        {"author", "title", "booktitle", "publisher", "year"},
        {
            "editor",
            "volume",
            "number",
            "series",
            "type",
            "chapter",
            "pages",
            "address",
            "edition",
            "month",
            "isbn",
            "note",
        },
    ),
    "inproceedings": (
        {"author", "title", "booktitle", "year"},
        {
            "editor",
            "volume",
            "number",
            "series",
            "pages",
            "address",
            "month",
            "organization",
            "publisher",
            "note",
        },
    ),
    "mastersthesis": _THESIS,
    "phdthesis": _THESIS,
    "techreport": (
        {"author", "title", "institution", "year"},
        {"type", "number", "address", "month", "note"},
    ),
    "unpublished": ({"author", "title", "note"}, {"month", "year"}),
    "misc": (set(), {"author", "title", "howpublished", "month", "year", "note"}),
}
_FILE_TYPES = {"application/pdf": "PDF", "text/html": "HTML"}
_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()  # noqa: SIM905


def write(export: Export) -> Written:
    paths = all_collections(export)
    groups, warnings = _group_names(paths)
    keys = _keys(export.papers)
    warnings += keyword_warning(export, "JabRef")
    warnings += notes_warning(export, "a .bib holds only papers.")
    blocks = []
    for key, paper in zip(keys, export.papers, strict=True):
        blocks.append(_entry(key, paper, groups))
        if len(paper.notes) > 1:
            warnings.append(
                f"The {len(paper.notes)} notes on {key} are one after the "
                "other in its Comments: JabRef has one comment per entry."
            )
    blocks.append("@Comment{jabref-meta: databaseType:bibtex;}\n")
    if paths:
        blocks.append(_grouping(paths, groups))
    return Written(
        content="\n".join(blocks).encode(),
        filename="paperus.bib",
        media_type="application/x-bibtex",
        warnings=warnings,
        readme=README,
    )


# Keys


def _keys(papers: list[ExportedPaper]) -> list[str]:
    """Each paper's own key, or ``AuthorYear``; repeats get a, b, … (as
    JabRef adds them), and an own key wins over a generated one."""
    own = [citations.own_key(paper.csl) for paper in papers]
    taken = {key for key in own if key}
    seen: set[str] = set()
    keys: list[str] = []
    for paper, own_key in zip(papers, own, strict=True):
        base = key = own_key or _generated_key(paper.csl)
        n = 0
        while key in seen or (key in taken and key != own_key):
            n += 1
            key = base + _letters(n)
        seen.add(key)
        keys.append(key)
    return keys


def _generated_key(csl: dict[str, Any]) -> str:
    tidy = citations.tidy(csl)
    names = tidy.get("author") or tidy.get("editor")
    name = names[0] if names else {}
    text = family(name) or str(name.get("literal") or name.get("given") or "")
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    author = re.sub(r"[^A-Za-z0-9]", "", ascii_)
    return (author[:1].upper() + author[1:] or "Anon") + (year(csl) or "")


def _letters(n: int) -> str:
    """1 → a, 26 → z, 27 → aa."""
    text = ""
    while n:
        n, rest = divmod(n - 1, 26)
        text = chr(ord("a") + rest) + text
    return text


# Groups


def _group_names(
    paths: list[tuple[str, ...]],
) -> tuple[dict[tuple[str, ...], str], list[str]]:
    """A JabRef group name per collection: unique, without the ``groups``
    field's separators."""
    names: dict[tuple[str, ...], str] = {}
    warnings: list[str] = []
    used: set[str] = set()
    for path in paths:
        name = _clean(path[-1]) or "Collection"
        if name in used and len(path) > 1:
            name = f"{name} ({_clean(path[-2])})"
        base, n = name, 1
        while name in used:
            n += 1
            name = f"{base} {n}"
        used.add(name)
        names[path] = name
        if name != path[-1]:
            warnings.append(
                f"The collection {' / '.join(path)} is the group {name!r}: "
                "JabRef tells groups apart by name and splits names at "
                "commas."
            )
    return names, warnings


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[,;]", " ", name)).strip()


def _grouping(paths: list[tuple[str, ...]], names: dict[tuple[str, ...], str]) -> str:
    """The groups tree as JabRef writes it: a line per group with its
    level; the name escaped for the line (``\\;``), the line for the
    comment (``;`` and ``\\`` again)."""
    tree = children(paths)
    lines = ["0 AllEntriesGroup:"]

    def add(path: tuple[str, ...]) -> None:
        # Name; hierarchy (0: independent); expanded; colour; icon; description.
        fields = [_quote(names[path], ";"), "0", "1", "", "", ""]
        lines.append(f"{len(path)} StaticGroup:" + ";".join(fields) + ";")
        for child in tree.get(path, []):
            add(child)

    for top in tree.get((), []):
        add(top)
    body = "".join(_quote(line, ";") + ";\n" for line in lines)
    return "@Comment{jabref-meta: grouping:\n" + body + "}\n"


def _quote(text: str, specials: str) -> str:
    """JabRef's escaping: a backslash before itself and the specials."""
    return re.sub(f"([\\\\{re.escape(specials)}])", r"\\\1", text)


# Entries


def _entry(key: str, paper: ExportedPaper, groups: dict[tuple[str, ...], str]) -> str:
    csl = citations.tidy(paper.csl)
    entry = citations.ENTRY_TYPES.get(str(csl.get("type") or ""), "misc")
    genre = first(csl.get("genre"))
    if entry == "phdthesis":
        kind = re.sub(r"\s|\.|thesis|unpublished", "", (genre or "").lower())
        if kind in citations.MASTERS:
            entry, genre = "mastersthesis", None
    fields: dict[str, str] = {}

    def add(name: str, value: object, *, text: bool = True) -> None:
        value = first(value)
        if value:
            fields[name] = "{" + (_latex(value, name) if text else _raw(value)) + "}"

    for role in ("author", "editor", "translator"):
        names = csl.get(role) or []
        if names:
            fields[role] = (
                "{" + " and ".join(citations.bibtex_name(n) for n in names) + "}"
            )
    add("title", csl.get("title") or "(untitled)")
    add("shorttitle", csl.get("title-short"))
    container = csl.get("container-title")
    if entry in ("incollection", "inproceedings"):
        add("booktitle", container)
    elif entry != "book":
        add("journal", container)
    add("year", year(csl))
    parts = date_parts(csl.get("issued"))
    if len(parts) > 1 and 1 <= parts[1] <= 12:
        fields["month"] = _MONTHS[parts[1] - 1]  # a macro: no braces
    if len(parts) > 2:
        add("date", iso_date(csl.get("issued")))
    add("volume", csl.get("volume"))
    add("number", csl.get("number") or csl.get("issue") or csl.get("collection-number"))
    page = first(csl.get("page"))
    add("pages", citations.DASHES.sub("--", page) if page else None)
    publisher = {"phdthesis": "school", "mastersthesis": "school"}.get(
        entry, "institution" if entry == "techreport" else "publisher"
    )
    add(publisher, csl.get("publisher"))
    add("address", csl.get("publisher-place"))
    add("edition", csl.get("edition"))
    add("series", csl.get("collection-title"))
    if entry in ("phdthesis", "techreport"):
        add("type", genre)
    add("doi", identifier(paper, Scheme.DOI), text=False)
    arxiv = arxiv_id(paper)
    if arxiv:
        add("eprint", arxiv, text=False)
        add("archiveprefix", "arXiv")
    add("pmid", identifier(paper, Scheme.PMID), text=False)
    add("isbn", identifier(paper, Scheme.ISBN), text=False)
    add("issn", csl.get("ISSN"), text=False)
    add("url", csl.get("URL"), text=False)
    add("urldate", iso_date(csl.get("accessed")))
    add("language", csl.get("language"))
    add("abstract", csl.get("abstract"))
    add("note", csl.get("note"))
    add("keywords", ", ".join(all_keywords(paper)))
    add("comment", "\n\n".join(note.strip() for note in paper.notes), text=False)
    add("file", ";".join(_file(file) for file in paper.files), text=False)
    add(
        "groups",
        ", ".join(dict.fromkeys(groups[path] for path in paper.collections)),
        text=False,
    )
    return _format(entry, key, fields)


def _format(entry: str, key: str, fields: dict[str, str]) -> str:
    required, optional = _FIELD_ORDER.get(entry, (set(), set()))
    order = sorted(fields, key=lambda f: (f not in required, f not in optional, f))
    width = max(len(name) for name in fields)
    lines = [f"@{_DISPLAY.get(entry, entry.capitalize())}{{{key},"]
    lines += [f"  {name.ljust(width)} = {fields[name]}," for name in order]
    return "\n".join([*lines, "}"]) + "\n"


def _file(file: ExportedFile) -> str:
    kind = _FILE_TYPES.get(file.media_type or "", file.media_type or "")
    return ":".join(
        _quote(part, ":;") for part in (file.description or "", file.path, kind)
    )


# Text

# Inline math as Pandoc reads it: no space inside the dollars, no digit
# after the closing one ("$5 and $10" is not math).
_MATH = re.compile(r"\$(?=[^\s$])(?:[^$\\]|\\.)*?(?<=[^\s\\])\$(?!\d)")
_PROTECTED = ("title", "shorttitle", "booktitle", "series")


def _latex(text: str, field: str) -> str:
    """Text for a field: LaTeX's special characters escaped, ``$…$`` math
    kept; in titles every word with a capital in braces."""
    out: list[str] = []
    at = 0
    for math in _MATH.finditer(text):
        if not citations.balanced(math.group()):
            continue
        out.append(_text(text[at : math.start()], field, at))
        out.append(math.group())
        at = math.end()
    out.append(_text(text[at:], field, at))
    return "".join(out)


def _text(text: str, field: str, at: int) -> str:
    escaped = citations.escape(text)
    if field not in _PROTECTED:
        return escaped
    # After math, the first word is not the title's first word.
    return (
        citations.protect(escaped) if at == 0 else citations.protect(" " + escaped)[1:]
    )


def _raw(text: str) -> str:
    """URLs, paths and Markdown as they are, but a stray brace would end
    the field early: those are percent-encoded."""
    return (
        text
        if citations.balanced(text)
        else text.replace("{", "%7B").replace("}", "%7D")
    )
