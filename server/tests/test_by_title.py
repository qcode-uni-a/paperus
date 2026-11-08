"""Papers without a DOI, found by their title at Crossref."""

from typing import Any

import httpx2

from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedPaper, by_title

TITLE = "Enhancement of Electric Drive in Silicon Quantum Dots"
DOI = "10.1103/gk5h-l7q4"


def crossref(*items: dict[str, Any]) -> tuple[httpx2.Client, list[str]]:
    asked: list[str] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        asked.append(request.url.params["query.bibliographic"])
        return httpx2.Response(200, json={"message": {"items": list(items)}})

    return httpx2.Client(transport=httpx2.MockTransport(answer)), asked


def found(**changes: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "DOI": DOI.upper(),
        "title": [TITLE.lower()],
        "author": [{"family": "Mai", "given": "Philip Y."}],
        "issued": {"date-parts": [[2025, 11, 5]]},
        "score": 45,
    } | changes


def paper(**changes: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "type": "article-journal",
        "title": TITLE,
        "author": [{"family": "Mai", "given": "Philip"}],
        "issued": {"date-parts": [[2024]]},
    } | changes


def test_found_by_title_first_author_and_year() -> None:
    http, asked = crossref(found())
    assert by_title.find_doi(http, paper()) == DOI
    assert asked == [f"{TITLE} Mai 2024"]


def test_only_a_sure_match() -> None:
    for other in (
        found(title=["Enhancement of electric drive in silicon"]),
        found(author=[{"family": "Pereira"}]),
        found(author=[]),
        found(issued={"date-parts": [[2021]]}),
        found(DOI="not a DOI"),
    ):
        http, _ = crossref(other)
        assert by_title.find_doi(http, paper()) is None, other
    # Nothing found; no year to compare.
    http, _ = crossref()
    assert by_title.find_doi(http, paper()) is None
    http, _ = crossref(found())
    assert by_title.find_doi(http, paper(issued=None)) == DOI


def test_not_asked_for_short_titles_or_web_pages() -> None:
    http, asked = crossref(found())
    assert by_title.find_doi(http, paper(title="Notes")) is None
    assert by_title.find_doi(http, paper(type="webpage")) is None
    assert asked == []


def test_an_import_brings_the_doi() -> None:
    http, asked = crossref(found())
    export = Export(
        format="bibtex",
        papers=[
            ExportedPaper(csl=paper()),
            ExportedPaper(
                csl=paper(title="Has one already, so not asked"),
                identifiers=[(Scheme.DOI, "10.1/x")],
            ),
            ExportedPaper(csl=paper(title="Too short")),
        ],
    )
    by_title.complete(export, http, pause=0)
    first = export.papers[0]
    assert first.identifiers == [(Scheme.DOI, DOI)]
    assert first.csl["DOI"] == DOI and first.csl["title"] == TITLE
    assert len(asked) == 1
    by_title.complete(export, None)  # no network: nothing
