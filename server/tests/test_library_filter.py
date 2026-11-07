"""The library's filter: the rules of smart collections, and authors."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.people import Person, group
from tests.test_smart_collections import paper, tag_ids


def test_filter_by_the_rules_of_smart_collections(
    client: TestClient, db: Session
) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    group(root, "Lab", ada)
    lab = ada.libraries()["Lab"]["id"]
    paper(ada, "Radar 2019", 2019, tags=("radar", "read"))
    paper(ada, "Radar 2023", 2023, tags=("radar",))
    paper(ada, "Rain book 2021", 2021, kind="book", tags=("rain",))
    paper(ada, "Group paper", 2022, library=lab)
    tags = tag_ids(ada)

    def titles(**params: Any) -> list[str]:  # noqa: ANN401
        response = ada.get("/api/items", params=params)
        assert response.status_code == 200, response.text
        assert response.headers["X-Total-Count"] == str(len(response.json()))
        return sorted(item["title"] for item in response.json())

    assert titles(tag=[tags["radar"], tags["read"]]) == ["Radar 2019"]
    assert titles(tag_any=[tags["read"], tags["rain"]]) == [
        "Radar 2019",
        "Rain book 2021",
    ]
    assert titles(tag=[tags["radar"]], tag_none=[tags["read"]]) == ["Radar 2023"]
    assert titles(type=["book"]) == ["Rain book 2021"]
    assert titles(published_from="2021-01-01", published_to="2022-12-31") == [
        "Group paper",
        "Rain book 2021",
    ]
    assert titles(owner=[lab]) == ["Group paper"]
    assert len(titles(added_days=1)) == 4
    assert ada.get("/api/items", params={"added_days": "0"}).status_code == 422


def test_filter_by_author(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")

    def add(title: str, *authors: dict[str, str]) -> str:
        response = ada.post(
            "/api/items",
            json={"metadata": {"title": title, "author": list(authors)}},
        )
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    add("Full name", {"family": "Benito", "given": "Mónica"})
    add("Initial", {"family": "benito", "given": "M."}, {"family": "Platero"})
    add("Another Benito", {"family": "Benito", "given": "Carlos"})
    add("A consortium", {"literal": "LIGO Scientific Collaboration"})
    edited = add("Edited", {"family": "Somebody"})
    etag = ada.get(f"/api/items/{edited}").headers["ETag"]
    response = client.put(
        f"/api/items/{edited}/overrides",
        json={"author": [{"family": "Benito", "given": "Mónica"}]},
        headers={**ada.headers, "If-Match": etag},
    )
    assert response.status_code == 200, response.text

    def titles(author: str) -> list[str]:
        response = ada.get("/api/items", params={"author": author})
        assert response.status_code == 200, response.text
        return sorted(item["title"] for item in response.json())

    # The family name and the given name's first letter, in any case.
    assert titles("Benito, Mónica") == ["Edited", "Full name", "Initial"]
    assert titles("Benito") == ["Another Benito", "Edited", "Full name", "Initial"]
    assert titles("Platero") == ["Initial"]
    assert titles("LIGO Scientific Collaboration") == ["A consortium"]
    assert titles("Nobody, A.") == []
