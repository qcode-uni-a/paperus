"""CSL-JSON (Zotero, Pandoc, citation tools) into the common form."""

import json
from typing import Any

from paperus.importing import Export, ExportedPaper
from paperus.importing.common import identifiers_of

# Fields CSL-JSON uses for an export's own purposes, not the paper's.
_INTERNAL = {"id", "_graph", "system_id"}


def read(text: str) -> Export:
    export = Export(format="csl-json")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        export.problems.append(f"The file is not valid JSON: {error}")
        return export
    entries = data.get("items", []) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        export.problems.append("The file holds no list of references.")
        return export
    for number, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or not entry.get("title"):
            export.problems.append(f"Entry {number} has no title and was skipped.")
            continue
        try:
            export.papers.append(_paper(number, entry))
        except Exception as error:
            export.problems.append(f"Entry {number} could not be read: {error}")
    return export


def _paper(number: int, entry: dict[str, Any]) -> ExportedPaper:
    csl = {k: v for k, v in entry.items() if k not in _INTERNAL}
    csl.setdefault("type", "document")
    key = entry.get("citation-key") or entry.get("id")
    if isinstance(key, str) and key and not key.startswith("http"):
        csl["citation-key"] = key
    identifiers = identifiers_of(
        doi=_first(entry.get("DOI")),
        isbn=_first(entry.get("ISBN")),
        pmid=_first(entry.get("PMID")),
        book=csl["type"] == "book",
    )
    return ExportedPaper(
        csl=csl, identifiers=identifiers, source_key=str(key or number)
    )


def _first(value: object) -> str | None:
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value else None
