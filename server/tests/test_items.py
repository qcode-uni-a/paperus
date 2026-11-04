import pytest
from fastapi.testclient import TestClient

from paperus.metadata import InvalidDOI, csl_type, normalize_doi
from tests.conftest import FakeDOIRegistry

DOI = "10.1038/s41586-020-2649-2"
CSL = {
    "type": "journal-article",
    "title": "Array programming with NumPy",
    "DOI": "10.1038/S41586-020-2649-2",
    "author": [
        {"family": "Harris", "given": "Charles R."},
        {"family": "Millman", "given": "K. Jarrod"},
        {"literal": "NumPy developers"},
    ],
    "container-title": "Nature",
    "issued": {"date-parts": [[2020, 9, 16]]},
}


@pytest.mark.parametrize(
    "value",
    [
        DOI,
        "10.1038/S41586-020-2649-2",
        " https://doi.org/10.1038/s41586-020-2649-2 ",
        "doi:10.1038/s41586-020-2649-2",
        "https://dx.doi.org/10.1038/s41586-020-2649-2",
    ],
)
def test_normalize_doi(value: str) -> None:
    assert normalize_doi(value) == DOI


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("journal-article", "article-journal"),
        ("proceedings-article", "paper-conference"),
        ("posted-content", "article"),
        ("article-journal", "article-journal"),
        ("software", "software"),
        (None, "document"),
    ],
)
def test_csl_type(given: str | None, expected: str) -> None:
    assert csl_type({"type": given}) == expected


@pytest.mark.parametrize("value", ["", "10.1/x", "not a doi", "11.1038/abc"])
def test_normalize_doi_rejects(value: str) -> None:
    with pytest.raises(InvalidDOI):
        normalize_doi(value)


def test_add_item_by_doi(logged_in: TestClient, doi_registry: FakeDOIRegistry) -> None:
    doi_registry.records[DOI] = CSL
    response = logged_in.post("/api/items", json={"doi": f"https://doi.org/{DOI}"})
    assert response.status_code == 201
    item = response.json()
    assert item["title"] == "Array programming with NumPy"
    assert item["type"] == "article-journal"
    assert item["doi"] == DOI
    assert item["authors"] == [
        "Harris, Charles R.",
        "Millman, K. Jarrod",
        "NumPy developers",
    ]
    assert item["year"] == 2020
    assert item["container_title"] == "Nature"
    assert item["csl"] == {**CSL, "type": "article-journal"}
    accept = doi_registry.requests[0].headers["Accept"]
    assert accept == "application/vnd.citationstyles.csl+json"

    assert logged_in.get(f"/api/items/{item['id']}").json() == item


def test_add_same_doi_returns_existing(
    logged_in: TestClient, doi_registry: FakeDOIRegistry
) -> None:
    doi_registry.records[DOI] = CSL
    first = logged_in.post("/api/items", json={"doi": DOI})
    second = logged_in.post("/api/items", json={"doi": DOI.upper()})
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len(doi_registry.requests) == 1


def test_add_item_errors(logged_in: TestClient) -> None:
    assert logged_in.post("/api/items", json={"doi": "nope"}).status_code == 422
    assert logged_in.post("/api/items", json={"doi": DOI}).status_code == 404


def test_lookup_failure(logged_in: TestClient, doi_registry: FakeDOIRegistry) -> None:
    doi_registry.records[DOI] = ["not", "an", "object"]
    assert logged_in.post("/api/items", json={"doi": DOI}).status_code == 502


def test_list_items_newest_first_with_paging(
    logged_in: TestClient, doi_registry: FakeDOIRegistry
) -> None:
    dois = [f"10.1234/paper.{n}" for n in range(3)]
    for n, doi in enumerate(dois):
        doi_registry.records[doi] = {"type": "article", "title": f"Paper {n}"}
        logged_in.post("/api/items", json={"doi": doi})

    page = logged_in.get("/api/items", params={"limit": 2}).json()
    assert [item["title"] for item in page] == ["Paper 2", "Paper 1"]
    rest = logged_in.get("/api/items", params={"before": page[-1]["id"]}).json()
    assert [item["title"] for item in rest] == ["Paper 0"]


def test_items_need_login(client: TestClient) -> None:
    assert client.get("/api/items").status_code == 401
    assert client.post("/api/items", json={"doi": DOI}).status_code == 401
