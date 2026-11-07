"""RIS, for Mendeley Reference Manager (and EndNote, Citavi and most other
reference managers, which all import RIS).

A record per paper: ``TY`` first, ``ER`` last, a line per field as
``XX  - value``, lines ending in CR LF as the RIS specification has them
(Mendeley, EndNote and Zotero also take LF), UTF-8. Authors ``AU`` and
editors ``A2`` as ``Family, Given``; title ``TI``; journal or book
``T2`` (journals also ``JO``); ``PY`` year and ``DA`` date
(``2024/03/02``); ``VL``, ``IS``, ``SP``/``EP``; ``PB``, ``CY``; ``SN``
(ISBN for books, ISSN otherwise); ``DO``; ``UR`` (also arXiv's page of
an arXiv paper); ``AB``; ``KW`` a line per tag, then the papers' own
keywords; ``N1`` a note each; ``L1`` a file each (its path, relative to
the .ris). Text over several lines (abstracts, notes) goes on in lines
without a tag, which RIS readers add to the field.

RIS has no collections and no notes without a paper, and Mendeley does
not take the files from RIS: the README says how to add them.
"""

import re

from paperus import citations
from paperus.formats.common import (
    Written,
    all_collections,
    all_keywords,
    arxiv_id,
    date_parts,
    family,
    first,
    given,
    identifier,
    iso_date,
    keyword_warning,
    notes_warning,
    year,
)
from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedPaper
from paperus.importing import ris as reader

README = """\
Mendeley Reference Manager (or EndNote, Citavi, …)
==================================================

paperus.ris holds your papers with their details, tags and keywords (both
as keywords), and notes. RIS has no collections, so they are not in it.

1. Unpack the whole archive.
2. In Mendeley Reference Manager: + Add new → Import library → RIS
   (*.ris), then choose paperus.ris (or drag the file into the window).
3. Mendeley does not take files from a RIS file. The PDFs are in the files
   folder: add each to its reference (open the reference and drag the PDF
   onto it), or add them all with + Add new → File(s) from computer, which
   makes new references from the PDFs that you may then need to merge with
   the imported ones.

EndNote and Citavi import the same file (about: File → Import, format
"RIS"); EndNote also links the files if the files folder stays next to
paperus.ris.
"""

# CSL type → RIS type: the importer's table the other way round (where two
# RIS types give one CSL type, the first).
_TYPES = {csl: ris for ris, csl in reversed(reader.TYPES.items())}
_BOOKS = {"book", "chapter"}
_TAG = re.compile(r"[A-Z][A-Z0-9]  -")


def write(export: Export) -> Written:
    lines = [line for paper in export.papers for line in _record(paper)]
    warnings = keyword_warning(export, "RIS")
    warnings += notes_warning(export, "RIS holds only papers.")
    if all_collections(export):
        warnings.append(
            "RIS has no collections (and Mendeley imports none): the papers "
            "come without them."
        )
    return Written(
        content="".join(line + "\r\n" for line in lines).encode(),
        filename="paperus.ris",
        media_type="application/x-research-info-systems",
        warnings=warnings,
        readme=README,
    )


def _record(paper: ExportedPaper) -> list[str]:
    csl = citations.tidy(paper.csl)
    kind = str(csl.get("type") or "")
    ris_type = _TYPES.get(kind, "GEN")
    lines: list[str] = []

    def add(tag: str, value: object) -> None:
        text = first(value)
        if not text:
            return
        rest = [line.rstrip() for line in text.splitlines()[1:] if line.strip()]
        lines.append(f"{tag}  - {text.splitlines()[0].strip()}")
        lines.extend(f" {line}" if _TAG.match(line) else line for line in rest)

    add("TY", ris_type)
    add("ID", citations.own_key(csl))
    for tag, role in (("AU", "author"), ("A2", "editor")):
        for name in csl.get(role) or []:
            add(tag, _name(name))
    add("TI", csl.get("title") or "(untitled)")
    add("T2", csl.get("container-title"))
    if ris_type == "JOUR":
        add("JO", csl.get("container-title"))
    add("J2", csl.get("container-title-short"))
    add("T3", csl.get("collection-title"))
    add("PY", year(csl))
    if len(date_parts(csl.get("issued"))) > 1:
        add("DA", iso_date(csl.get("issued"), "/"))
    add("VL", csl.get("volume"))
    add("IS", csl.get("issue") or csl.get("number"))
    pages = citations.DASHES.split(first(csl.get("page")) or "", maxsplit=1)
    add("SP", pages[0])
    add("EP", pages[1] if len(pages) > 1 else None)
    add("ET", csl.get("edition"))
    add("PB", csl.get("publisher"))
    add("CY", csl.get("publisher-place"))
    add(
        "SN",
        identifier(paper, Scheme.ISBN) if kind in _BOOKS else csl.get("ISSN"),
    )
    add("DO", identifier(paper, Scheme.DOI))
    urls = [first(csl.get("URL"))]
    arxiv = arxiv_id(paper)
    if arxiv:
        urls.append(f"https://arxiv.org/abs/{arxiv}")
    for url in dict.fromkeys(url for url in urls if url):
        add("UR", url.replace(";", "%3B"))  # ; separates URLs in RIS
    add("LA", csl.get("language"))
    add("AB", csl.get("abstract"))
    for word in all_keywords(paper):
        add("KW", word)
    for note in paper.notes:
        add("N1", note)
    for file in paper.files:
        add("L1", file.path)
    lines.append("ER  - ")
    lines.append("")
    return lines


def _name(name: dict[str, object]) -> str:
    if name.get("literal") or not name.get("family"):
        return str(name.get("literal") or name.get("given") or "")
    parts = [family(name)]
    if given(name) or name.get("suffix"):
        parts.append(given(name))
    if name.get("suffix"):
        parts.append(str(name["suffix"]))
    return ", ".join(parts)
