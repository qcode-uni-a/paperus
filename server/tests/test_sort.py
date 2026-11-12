"""The library sorted: by title, first author, year, publication date,
journal or when added, either way; papers without the value last."""

from typing import Any

from fastapi.testclient import TestClient


def add(client: TestClient, metadata: dict[str, Any]) -> str:
    response = client.post("/api/items", json={"metadata": metadata})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def titles(client: TestClient, **query: str | int) -> list[str]:
    response = client.get("/api/items", params=query)
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()]


def library(client: TestClient) -> None:
    """Four papers, added in this order."""
    add(
        client,
        {
            "title": "Zebra stripes",
            "author": [{"family": "Ölund", "given": "Eva"}],
            "container-title": ["Nature"],
            "issued": {"date-parts": [[2021, 3, 5]]},
        },
    )
    add(
        client,
        {
            "title": "<i>Arabidopsis</i> roots",
            "author": [{"family": "brown", "given": "Ann"}],
            "container-title": "cell",
            "issued": {"date-parts": [[2021, 1]]},
        },
    )
    add(
        client,
        {
            "title": "Meeting notes",
            "author": [{"literal": "The Lab"}],
            "issued": {"date-parts": [[2019]]},
        },
    )
    add(client, {"title": "Untitled draft"})


def test_by_each_field(logged_in: TestClient) -> None:
    library(logged_in)
    zebra, roots, notes, draft = (
        "Zebra stripes",
        "<i>Arabidopsis</i> roots",
        "Meeting notes",
        "Untitled draft",
    )
    assert titles(logged_in) == [draft, notes, roots, zebra]
    assert titles(logged_in, sort="added", order="asc") == [zebra, roots, notes, draft]
    # Without markup, any case.
    assert titles(logged_in, sort="title") == [roots, notes, draft, zebra]
    assert titles(logged_in, sort="title", order="desc") == [zebra, draft, notes, roots]
    # Accents as the language has them; none last, either way.
    assert titles(logged_in, sort="author") == [roots, zebra, notes, draft]
    assert titles(logged_in, sort="author", order="desc") == [
        notes,
        zebra,
        roots,
        draft,
    ]
    # The same year: by first author.
    assert titles(logged_in, sort="year") == [roots, zebra, notes, draft]
    assert titles(logged_in, sort="year", order="asc") == [notes, roots, zebra, draft]
    assert titles(logged_in, sort="published") == [zebra, roots, notes, draft]
    assert titles(logged_in, sort="published", order="asc") == [
        notes,
        roots,
        zebra,
        draft,
    ]
    assert titles(logged_in, sort="journal") == [roots, zebra, notes, draft]
    assert titles(logged_in, sort="journal", order="desc")[:2] == [zebra, roots]

    # Paged by offset.
    assert titles(logged_in, sort="title", limit=2, offset=2) == [draft, zebra]


def test_edits_sort_too(logged_in: TestClient) -> None:
    library(logged_in)
    item_id = add(
        logged_in,
        {"title": "Quantum dots", "author": [{"family": "Young", "given": "Al"}]},
    )
    assert titles(logged_in, sort="author")[3] == "Quantum dots"
    item = logged_in.get(f"/api/items/{item_id}")
    edited = logged_in.put(
        f"/api/items/{item_id}/overrides",
        json={
            "author": [{"family": "Abel", "given": "Al"}],
            "container-title": "Annals",
        },
        headers={"If-Match": item.headers["ETag"]},
    )
    assert edited.status_code == 200, edited.text
    assert titles(logged_in, sort="author")[0] == "Quantum dots"
    assert titles(logged_in, sort="journal")[0] == "Quantum dots"
