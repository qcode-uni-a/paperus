from typing import Any

import pytest
from fastapi.testclient import TestClient

from paperus.metadata import csl_type
from tests.conftest import FakeDOIRegistry

DOI = "10.1038/s41586-020-2649-2"
PREPRINT_DOI = "10.48550/arxiv.2006.10256"
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
PREPRINT_CSL = {
    "type": "article-journal",
    "title": "Array Programming with NumPy",
    "author": [{"family": "Harris", "given": "Charles R."}],
    "issued": {"date-parts": [[2020, 6, 18]]},
}
MEETING = {
    "type": "document",
    "genre": "Meeting notes",
    "title": "Group meeting: pilot planning",
    "author": [{"literal": "Climate group"}],
    "issued": {"date-parts": [[2026, 11, 4]]},
}


@pytest.fixture
def registry(doi_registry: FakeDOIRegistry) -> FakeDOIRegistry:
    doi_registry.records[DOI] = CSL
    doi_registry.records[PREPRINT_DOI] = PREPRINT_CSL
    return doi_registry


def post(
    client: TestClient, url: str, body: dict[str, Any], status: int
) -> dict[str, Any]:
    response = client.post(url, json=body)
    assert response.status_code == status, response.text
    result: dict[str, Any] = response.json()
    return result


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


def test_add_item_by_doi(logged_in: TestClient, registry: FakeDOIRegistry) -> None:
    item = post(logged_in, "/api/items", {"doi": f"https://doi.org/{DOI}"}, 201)
    assert item["title"] == "Array programming with NumPy"
    assert item["type"] == "article-journal"
    assert item["authors"] == [
        "Harris, Charles R.",
        "Millman, K. Jarrod",
        "NumPy developers",
    ]
    assert item["year"] == 2020
    assert item["container_title"] == "Nature"
    assert item["identifiers"] == [{"scheme": "doi", "value": DOI}]
    [version] = item["versions"]
    assert version["kind"] == "published"
    assert version["metadata_source"] == "lookup"
    assert version["csl"] == {**CSL, "type": "article-journal"}
    assert item["preferred_version_id"] == version["id"]
    accept = registry.requests[0].headers["Accept"]
    assert accept == "application/vnd.citationstyles.csl+json"

    assert logged_in.get(f"/api/items/{item['id']}").json() == item


def test_known_identifier_returns_existing_item(
    logged_in: TestClient, registry: FakeDOIRegistry
) -> None:
    first = post(logged_in, "/api/items", {"doi": DOI}, 201)
    second = post(logged_in, "/api/items", {"doi": DOI.upper()}, 200)
    assert second["id"] == first["id"]
    assert len(registry.requests) == 1


def test_preprint_and_published_versions(
    logged_in: TestClient, registry: FakeDOIRegistry
) -> None:
    item = post(logged_in, "/api/items", {"doi": PREPRINT_DOI}, 201)
    [preprint] = item["versions"]
    assert preprint["kind"] == "preprint"
    assert preprint["csl"]["type"] == "article"
    assert {"scheme": "arxiv", "value": "2006.10256"} in preprint["identifiers"]
    assert item["title"] == "Array Programming with NumPy"

    item = post(logged_in, f"/api/items/{item['id']}/versions", {"doi": DOI}, 201)
    published = item["versions"][1]
    assert published["kind"] == "published"
    assert item["preferred_version_id"] == published["id"]
    assert item["title"] == "Array programming with NumPy"
    assert item["container_title"] == "Nature"

    # The arXiv ID now finds the same item.
    again = post(
        logged_in,
        "/api/items",
        {
            "metadata": {"title": "x"},
            "identifiers": [{"scheme": "arxiv", "value": "arXiv:2006.10256v2"}],
        },
        200,
    )
    assert again["id"] == item["id"]

    pinned = logged_in.post(f"/api/versions/{preprint['id']}/pin").json()
    assert pinned["preferred_version_id"] == preprint["id"]
    assert pinned["title"] == "Array Programming with NumPy"
    repinned = logged_in.post(f"/api/versions/{published['id']}/pin").json()
    assert repinned["preferred_version_id"] == published["id"]


def test_identifier_of_another_item_conflicts(
    logged_in: TestClient, registry: FakeDOIRegistry
) -> None:
    published = post(logged_in, "/api/items", {"doi": DOI}, 201)
    preprint = post(logged_in, "/api/items", {"doi": PREPRINT_DOI}, 201)
    response = logged_in.post(
        f"/api/items/{preprint['id']}/versions", json={"doi": DOI}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["item_id"] == published["id"]
    # The same identifier on the same item is fine.
    post(logged_in, f"/api/items/{published['id']}/versions", {"doi": DOI}, 200)


def test_meeting_notes_without_identifier(logged_in: TestClient) -> None:
    item = post(logged_in, "/api/items", {"metadata": MEETING}, 201)
    assert item["type"] == "document"
    assert item["title"] == "Group meeting: pilot planning"
    assert item["year"] == 2026
    assert item["identifiers"] == []
    [version] = item["versions"]
    assert version["kind"] == "other"
    assert version["metadata_source"] == "manual"
    assert item["csl"]["genre"] == "Meeting notes"


def test_lecture_notes_editions(logged_in: TestClient) -> None:
    notes = {"type": "document", "genre": "Lecture notes", "title": "Hydrology I"}
    item = post(
        logged_in,
        "/api/items",
        {"metadata": notes, "kind": "edition", "label": "WS 2025/26"},
        201,
    )
    item = post(
        logged_in,
        f"/api/items/{item['id']}/versions",
        {
            "metadata": {**notes, "title": "Hydrology I (revised)"},
            "kind": "edition",
            "label": "WS 2026/27",
        },
        201,
    )
    assert [v["label"] for v in item["versions"]] == ["WS 2025/26", "WS 2026/27"]
    # Newest edition is preferred.
    assert item["preferred_version_id"] == item["versions"][1]["id"]
    assert item["title"] == "Hydrology I (revised)"


def test_book_by_isbn(logged_in: TestClient) -> None:
    book = {"type": "book", "title": "Hydrology", "edition": "2"}
    body = {
        "metadata": book,
        "kind": "edition",
        "label": "2nd edition",
        "identifiers": [{"scheme": "isbn", "value": "0-306-40615-2"}],
    }
    item = post(logged_in, "/api/items", body, 201)
    assert item["identifiers"] == [{"scheme": "isbn", "value": "9780306406157"}]
    body["identifiers"] = [{"scheme": "isbn", "value": "978-0-306-40615-7"}]
    assert post(logged_in, "/api/items", body, 200)["id"] == item["id"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"doi": DOI, "metadata": MEETING},
        {"metadata": {"type": "document"}},
        {"doi": "not a doi"},
        {"metadata": MEETING, "identifiers": [{"scheme": "isbn", "value": "123"}]},
        {"metadata": MEETING, "kind": "final"},
    ],
)
def test_invalid_requests(logged_in: TestClient, body: dict[str, Any]) -> None:
    assert logged_in.post("/api/items", json=body).status_code == 422


def test_lookup_errors(logged_in: TestClient, doi_registry: FakeDOIRegistry) -> None:
    assert logged_in.post("/api/items", json={"doi": DOI}).status_code == 404
    doi_registry.records[DOI] = ["not", "an", "object"]
    assert logged_in.post("/api/items", json={"doi": DOI}).status_code == 502


def test_list_items_newest_first_with_paging(logged_in: TestClient) -> None:
    for n in range(3):
        post(logged_in, "/api/items", {"metadata": {"title": f"Note {n}"}}, 201)
    page = logged_in.get("/api/items", params={"limit": 2}).json()
    assert [item["title"] for item in page] == ["Note 2", "Note 1"]
    rest = logged_in.get("/api/items", params={"before": page[-1]["id"]}).json()
    assert [item["title"] for item in rest] == ["Note 0"]


def test_items_need_login(client: TestClient) -> None:
    assert client.get("/api/items").status_code == 401
    assert client.post("/api/items", json={"doi": DOI}).status_code == 401
