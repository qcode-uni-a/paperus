"""RIS (Mendeley, EndNote, Citavi, publishers) into the common form."""

import re
from typing import Any

import rispy

from paperus.importing import Export, ExportedFile, ExportedPaper
from paperus.importing.common import date_parts, identifiers_of

# RIS reference type → CSL type (anything else: document).
TYPES = {
    "JOUR": "article-journal",
    "JFULL": "article-journal",
    "EJOUR": "article-journal",
    "MGZN": "article-magazine",
    "NEWS": "article-newspaper",
    "CONF": "paper-conference",
    "CPAPER": "paper-conference",
    "BOOK": "book",
    "EBOOK": "book",
    "EDBOOK": "book",
    "CHAP": "chapter",
    "ECHAP": "chapter",
    "THES": "thesis",
    "RPRT": "report",
    "UNPB": "manuscript",
    "MANSCPT": "manuscript",
    "ELEC": "webpage",
    "WEB": "webpage",
    "PAT": "patent",
    "DATA": "dataset",
    "COMP": "software",
}

_LISTS = [*rispy.LIST_TYPE_TAGS, "L1", "L2", "N2", "SN", "DO"]


class _Parser(rispy.RisParser):
    """rispy, but a note over several lines (EndNote's, paperus') stays one
    note with its line breaks and indents, not a note per line."""

    def parse_line(self, line: str) -> tuple[str, str] | tuple[None, str]:
        tag, content = super().parse_line(line)
        return (tag, content) if tag is not None else (None, line.rstrip())

    def _add_tag(
        self, record: dict, tag: str, content: str, extend_multiline: bool = False
    ) -> None:
        if extend_multiline and tag == "N1" and record.get("notes"):
            record["notes"][-1] += "\n" + content
            return
        if extend_multiline:
            content = content.strip()
        super()._add_tag(record, tag, content, extend_multiline)


def read(text: str) -> Export:
    export = Export(format="ris")
    try:
        entries = rispy.loads(
            text, implementation=_Parser, list_tags=_LISTS, skip_unknown_tags=True
        )
    except Exception as error:
        export.problems.append(f"The file could not be read as RIS: {error}")
        return export
    for number, entry in enumerate(entries, 1):
        try:
            export.papers.append(_paper(number, entry))
        except Exception as error:
            export.problems.append(f"Entry {number} could not be read: {error}")
    return export


def _first(entry: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, list):
            value = next((v for v in value if v and str(v).strip()), None)
        if value and str(value).strip():
            return str(value).strip()
    return None


def _name(text: str) -> dict[str, str]:
    """RIS names: ``Family, Given`` (``Family, Given, Suffix``)."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) == 1:
        return {"literal": parts[0]}
    name = {"family": parts[0], "given": parts[1]}
    if len(parts) > 2 and parts[2]:
        name["suffix"] = parts[2]
    return name


def _paper(number: int, entry: dict[str, Any]) -> ExportedPaper:
    ris_type = str(entry.get("type_of_reference") or "GEN").upper()
    csl: dict[str, Any] = {"type": TYPES.get(ris_type, "document")}
    csl["title"] = (
        _first(entry, "title", "primary_title", "translated_title") or "(untitled)"
    )
    authors = [*entry.get("authors", []), *entry.get("first_authors", [])]
    if authors:
        csl["author"] = [_name(a) for a in authors]
    # A2 is the book's editor for chapters and books, other people for
    # other types (a journal article's, for one, in some programs).
    editors = (
        entry.get("secondary_authors", []) if csl["type"] in ("chapter", "book") else []
    )
    if editors:
        csl["editor"] = [_name(e) for e in editors]
    container = _first(
        entry, "secondary_title", "journal_name", "alternate_title3", "alternate_title1"
    )
    if container and csl["type"] not in ("book", "webpage"):
        csl["container-title"] = container
    issued = date_parts(_first(entry, "date")) or date_parts(
        year=_first(entry, "year", "publication_year")
    )
    if issued:
        csl["issued"] = issued
    pages = [_first(entry, "start_page"), _first(entry, "end_page")]
    if pages[0]:
        csl["page"] = "-".join(p for p in pages if p)
    for csl_name, keys in {
        "volume": ("volume",),
        "issue": ("number",),
        "publisher": ("publisher",),
        "publisher-place": ("place_published",),
        "edition": ("edition",),
        "collection-title": ("tertiary_title",),
        "abstract": ("abstract", "notes_abstract"),
        "language": ("language",),
        "URL": ("urls",),
    }.items():
        value = _first(entry, *keys)
        if value:
            csl[csl_name] = value
    serial = _first(entry, "issn")
    if serial:
        csl["ISBN" if csl["type"] in ("book", "chapter") else "ISSN"] = serial
    doi_text = _first(entry, "doi")
    identifiers = identifiers_of(
        doi=doi_text,
        arxiv=_arxiv(entry),
        isbn=csl.get("ISBN"),
        book=csl["type"] == "book",
    )
    if csl["type"] == "document" and any(s.value == "arxiv" for s, _ in identifiers):
        csl["type"] = "article"
    doi = next((v for s, v in identifiers if s.value == "doi"), None)
    if doi:
        csl["DOI"] = doi
    files = [
        ExportedFile(path=_file_path(path))
        for key in ("file_attachments1", "file_attachments2")
        for path in entry.get(key, [])
        if path and path.strip()
    ]
    return ExportedPaper(
        csl=csl,
        identifiers=identifiers,
        tags=[k.strip() for k in entry.get("keywords", []) if k and k.strip()],
        notes=[n.strip() for n in entry.get("notes", []) if n and n.strip()],
        files=files,
        source_key=str(entry.get("id") or number),
    )


def _arxiv(entry: dict[str, Any]) -> str | None:
    for url in entry.get("urls", []):
        found = re.search(r"arxiv\.org/(?:abs|pdf)/([^\s/?#]+?)(?:\.pdf)?$", url or "")
        if found:
            return found.group(1)
    return None


def _file_path(value: str) -> str:
    """``file:///C:/x.pdf`` or ``internal-pdf://…/x.pdf`` → a path."""
    value = value.strip()
    value = re.sub(r"^file://(localhost)?", "", value)
    value = re.sub(r"^internal-pdf://(\d+/)?", "", value)
    return re.sub(r"%20", " ", value)
