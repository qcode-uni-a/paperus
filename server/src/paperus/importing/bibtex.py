"""BibTeX and BibLaTeX (JabRef, Zotero, Mendeley, …) into the common form.

JabRef's groups (``@Comment{jabref-meta: grouping: …}`` and the ``groups``
field) become collections, ``keywords`` tags (from Mendeley, its
``mendeley-tags``, the authors' keywords kept apart as keywords),
``annote``/``comment`` notes,
``file`` links files; the entry key is kept as the citation key.
"""

import re
from typing import Any

from pybtex.database import BibliographyData, Entry, Person, parse_string
from pybtex.scanner import PybtexSyntaxError
from pylatexenc.latex2text import LatexNodes2Text

from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedFile, ExportedPaper
from paperus.importing.common import date_parts, identifiers_of, split_keywords

# BibTeX/BibLaTeX entry type → CSL type (anything else: document).
_TYPES = {
    "article": "article-journal",
    "inproceedings": "paper-conference",
    "conference": "paper-conference",
    "proceedings": "book",
    "book": "book",
    "mvbook": "book",
    "booklet": "book",
    "inbook": "chapter",
    "incollection": "chapter",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
    "manual": "report",
    "unpublished": "manuscript",
    "online": "webpage",
    "electronic": "webpage",
    "www": "webpage",
    "patent": "patent",
    "dataset": "dataset",
    "software": "software",
    "misc": "document",
}

_MONTHS = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)
_latex = LatexNodes2Text(math_mode="verbatim", keep_comments=False)


def plain(value: str) -> str:
    """LaTeX to Unicode text (``M{\\"u}ller`` → ``Müller``), braces gone,
    math kept as written (``$\\alpha$``)."""
    try:
        text = _latex.latex_to_text(value)
    except Exception:  # pylatexenc gives up on odd input; keep it readable
        text = value.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def read(text: str) -> Export:
    export = Export(format="bibtex")
    try:
        data = parse_string(_without_comments(text), "bibtex")
    except PybtexSyntaxError as error:
        export.problems.append(f"The file could not be read as BibTeX: {error}")
        return export
    except Exception as error:  # pybtex raises plain errors, e.g. duplicate keys
        data = _parse_leniently(text, export)
        if data is None:
            export.problems.append(f"The file could not be read as BibTeX: {error}")
            return export
    groups = _jabref_groups(text)
    export.collections = list(dict.fromkeys(groups.values()))
    for key, entry in data.entries.items():
        try:
            export.papers.append(_paper(key, entry, groups))
        except Exception as error:
            export.problems.append(f"Entry {key} could not be read: {error}")
    return export


def _without_comments(text: str) -> str:
    """pybtex reads @Comment blocks as entries in some versions."""
    return re.sub(r"@comment\s*\{jabref-meta:.*?\n\}", "", text, flags=re.I | re.S)


def _parse_leniently(text: str, export: Export) -> BibliographyData | None:
    """Read entry by entry, so one broken or repeated entry does not stop the
    rest; a repeated key gets a suffix."""
    data = BibliographyData()
    for chunk in re.split(r"(?=^\s*@)", _without_comments(text), flags=re.M):
        if not chunk.strip().startswith("@"):
            continue
        try:
            part = parse_string(chunk, "bibtex")
        except Exception as error:
            export.problems.append(f"An entry could not be read: {error}")
            continue
        for key, entry in part.entries.items():
            unique, n = key, 1
            while unique in data.entries:
                n += 1
                unique = f"{key}-{n}"
            if unique != key:
                export.problems.append(
                    f"The key {key} appears more than once; also imported as {unique}."
                )
            data.entries[unique] = entry
    return data if data.entries else None


def _jabref_groups(text: str) -> dict[str, tuple[str, ...]]:
    """JabRef's static groups: name → path of names from the top."""
    found = re.search(
        r"@comment\s*\{jabref-meta:\s*grouping:(.*?)\n\}", text, flags=re.I | re.S
    )
    if not found:
        return {}
    paths: dict[str, tuple[str, ...]] = {}
    stack: list[str] = []
    for line in re.split(r";\s*\n", found.group(1)):
        match = re.match(r"\s*(\d+)\s+(\w+):(.*)", line.strip())
        if not match:
            continue
        level, kind, rest = int(match.group(1)), match.group(2), match.group(3)
        if level == 0:  # AllEntriesGroup
            continue
        # Fields are separated by "\;", the first is the name.
        name = rest.split("\\;")[0].replace("\\\\", "\\").strip()
        del stack[level - 1 :]
        stack.append(name)
        if kind in ("StaticGroup", "ExplicitGroup"):
            paths[name] = tuple(stack)
    return paths


def _paper(key: str, entry: Entry, groups: dict[str, tuple[str, ...]]) -> ExportedPaper:
    fields = {name.lower(): value for name, value in (entry.fields or {}).items()}

    def get(*names: str) -> str | None:
        for name in names:
            value = fields.get(name)
            if value and value.strip():
                return plain(value)
        return None

    entry_type = (entry.type or "misc").lower()
    csl: dict[str, Any] = {"type": _TYPES.get(entry_type, "document")}
    if entry_type == "misc" and get("eprint") and _is_arxiv(fields):
        csl["type"] = "article"
    csl["title"] = get("title") or "(untitled)"
    for role in ("author", "editor", "translator"):
        persons = entry.persons or {}
        people = persons.get(role) or persons.get(role.capitalize())
        if people:
            csl[role] = [_name(person) for person in people]
    container = get("journaltitle", "journal", "booktitle")
    if container:
        csl["container-title"] = container
    issued = date_parts(get("date"), get("year"), _month(fields.get("month")))
    if issued:
        csl["issued"] = issued
    for csl_name, names in {
        "volume": ("volume",),
        "issue": ("number", "issue")
        if csl["type"] == "article-journal"
        else ("issue",),
        "number": () if csl["type"] == "article-journal" else ("number",),
        "page": ("pages",),
        "publisher": ("publisher", "school", "institution", "organization"),
        "publisher-place": ("address", "location"),
        "edition": ("edition",),
        "collection-title": ("series",),
        "abstract": ("abstract",),
        "language": ("language", "langid"),
        "ISBN": ("isbn",),
        "ISSN": ("issn",),
        "URL": ("url",),
        "note": ("note",),
        "genre": ("type",),
    }.items():
        value = get(*names)
        if value:
            csl[csl_name] = value
    if csl["type"] == "thesis" and "genre" not in csl:
        csl["genre"] = (
            "Master's thesis" if entry_type == "mastersthesis" else "PhD thesis"
        )
    if "page" in csl:
        csl["page"] = re.sub(r"\s*[-\u2013\u2014]+\s*", "-", csl["page"])
    accessed = date_parts(get("urldate"))
    if accessed:
        csl["accessed"] = accessed
    doi = get("doi")
    csl["citation-key"] = key

    arxiv = get("eprint") if _is_arxiv(fields) else None
    identifiers = identifiers_of(
        doi=doi,
        arxiv=arxiv,
        isbn=csl.get("ISBN"),
        pmid=get("pmid"),
        book=csl["type"] == "book",
    )
    found_doi = next((v for s, v in identifiers if s == Scheme.DOI), None)
    if found_doi or doi:
        csl["DOI"] = found_doi or doi
    keywords = split_keywords(get("keywords") or "")
    tags = keywords
    automatic: list[str] = []
    if "mendeley-tags" in fields:
        # Mendeley writes the person's tags here, and in ``keywords`` also
        # the authors' keywords.
        tags = split_keywords(get("mendeley-tags") or "")
        own = {tag.casefold() for tag in tags}
        automatic = [word for word in keywords if word.casefold() not in own]
    paper = ExportedPaper(
        csl=csl,
        identifiers=identifiers,
        tags=tags,
        keywords=automatic,
        notes=[note for note in (get("annote"), get("comment")) if note],
        files=_files(fields.get("file", "")),
        source_key=key,
    )
    for name in split_keywords(fields.get("groups", "")):
        paper.collections.append(groups.get(name, (name,)))
    return paper


def _is_arxiv(fields: dict[str, str]) -> bool:
    prefix = (fields.get("archiveprefix") or fields.get("eprinttype") or "").lower()
    return prefix == "arxiv"


def _month(value: str | None) -> int | None:
    if not value:
        return None
    value = value.strip().lower()
    if value.isdecimal():  # not isdigit: int() refuses "²"
        return int(value)
    for number, name in enumerate(_MONTHS, 1):
        if value.startswith(name):
            return number
    return None


def _name(person: Person) -> dict[str, str]:
    given = " ".join([*_parts(person.first_names), *_parts(person.middle_names)])
    family = " ".join(_parts(person.last_names))
    if not given and not _parts(person.prelast_names) and family.startswith("{"):
        return {"literal": plain(family)}
    name = {"family": plain(family)}
    if given:
        name["given"] = plain(given)
    if _parts(person.prelast_names):
        name["non-dropping-particle"] = plain(" ".join(_parts(person.prelast_names)))
    if _parts(person.lineage_names):
        name["suffix"] = plain(" ".join(_parts(person.lineage_names)))
    return name


def _parts(names: object) -> list[str]:
    return [str(n) for n in names] if isinstance(names, list) else []


def _files(value: str) -> list[ExportedFile]:
    """JabRef/Zotero/Mendeley ``file`` field: ``description:path:type``
    records separated by ``;``, with ``\\:`` and ``\\;`` escaped. Zotero
    and Mendeley sometimes write bare paths."""
    files: list[ExportedFile] = []
    for record in re.split(r"(?<!\\);", value):
        record = record.strip()
        if not record:
            continue
        parts = [
            p.replace("\\:", ":").replace("\\;", ";")
            for p in re.split(r"(?<!\\):", record)
        ]
        if len(parts) >= 3:
            description, path, kind = parts[0], ":".join(parts[1:-1]), parts[-1]
        else:
            description, path, kind = "", ":".join(parts), ""
        path = path.replace("\\\\", "\\").strip()
        if path:
            files.append(
                ExportedFile(
                    path=path,
                    media_type=_media_type(kind),
                    description=description or None,
                )
            )
    return files


def _media_type(kind: str) -> str | None:
    kind = kind.strip().lower()
    if "/" in kind:
        return kind
    return {"pdf": "application/pdf", "html": "text/html"}.get(kind)
