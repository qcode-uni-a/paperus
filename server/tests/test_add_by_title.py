"""Papers listed without identifiers (a Google Scholar profile): found in the
library by their title, added by the DOI their title finds at Crossref."""

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import FakeDOIRegistry

TITLE = "Enhancement of Electric Drive in Silicon Quantum Dots"
DOI = "10.1103/gk5h-l7q4"
LISTED = {
    "type": "article-journal",
    "title": TITLE,
    "author": [{"family": "Mai", "given": "PY"}, {"family": "Benito", "given": "M"}],
    "container-title": "Physical Review B",
    "issued": {"date-parts": [[2025]]},
}
REGISTERED = {
    "type": "journal-article",
    "title": TITLE,
    "DOI": DOI,
    "author": [
        {"family": "Mai", "given": "Philip Y."},
        {"family": "Benito", "given": "Mónica"},
    ],
    "container-title": "Physical Review B",
    "issued": {"date-parts": [[2025, 11, 5]]},
}


def crossref_finds(registry: FakeDOIRegistry, *items: dict[str, Any]) -> None:
    # The fake registry answers every address by its path: Crossref's search
    # is /works.
    registry.records["works"] = {"message": {"items": list(items)}}


def add(client: TestClient, body: dict[str, Any], status: int) -> dict[str, Any]:
    response = client.post("/api/items", json=body)
    assert response.status_code == status, response.text
    result: dict[str, Any] = response.json()
    return result


def test_added_by_the_doi_its_title_finds(
    logged_in: TestClient, doi_registry: FakeDOIRegistry
) -> None:
    crossref_finds(
        doi_registry,
        {**REGISTERED, "title": [TITLE.upper()], "issued": {"date-parts": [[2026]]}},
    )
    doi_registry.records[DOI] = REGISTERED
    item = add(logged_in, {"metadata": LISTED, "find_doi": True}, 201)
    assert item["identifiers"][0] == {"scheme": "doi", "value": DOI}
    # The registry's details, not the profile's initials.
    assert item["authors"][0] == "Mai, Philip Y."

    # Listed again: the paper one has.
    again = add(logged_in, {"metadata": LISTED, "find_doi": True}, 200)
    assert again["id"] == item["id"]


def test_without_a_sure_match_as_given(
    logged_in: TestClient, doi_registry: FakeDOIRegistry
) -> None:
    # Another first author: not this paper.
    crossref_finds(
        doi_registry, {**REGISTERED, "author": [{"family": "Smith", "given": "A"}]}
    )
    item = add(logged_in, {"metadata": LISTED, "find_doi": True}, 201)
    assert item["identifiers"] == []
    assert item["title"] == TITLE

    # Asked for nothing: Crossref is not asked.
    asked = len(doi_registry.requests)
    add(logged_in, {"metadata": {**LISTED, "title": "Another paper on qubits"}}, 201)
    assert len(doi_registry.requests) == asked


def test_a_doi_its_registry_does_not_know(
    logged_in: TestClient, doi_registry: FakeDOIRegistry
) -> None:
    crossref_finds(doi_registry, REGISTERED)  # but doi.org has no record
    item = add(logged_in, {"metadata": LISTED, "find_doi": True}, 201)
    assert item["identifiers"] == []
    assert item["authors"][0] == "Mai, PY"


def test_found_by_title(logged_in: TestClient) -> None:
    add(logged_in, {"metadata": {**LISTED, "title": f"<i>{TITLE}</i>"}}, 201)
    keys = [
        f"title:{TITLE.upper()}.",
        "title:Enhancement of electric drive",
        "title:Quantum dots",
        "doi:10.1/none",
    ]
    response = logged_in.get("/api/items/lookup", params={"id": keys})
    assert response.status_code == 200, response.text
    found = response.json()
    assert found[keys[0]] is not None
    assert found[keys[1]] is None  # another title
    assert found[keys[2]] is None  # too short to tell
    assert found[keys[3]] is None
