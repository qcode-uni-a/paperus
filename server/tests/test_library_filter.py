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


def test_filter_by_journal(client: TestClient, db: Session) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")

    def add(person: Person, title: str, journal: str | None) -> None:
        metadata = {"title": title, **({"container-title": journal} if journal else {})}
        person.post("/api/items", json={"metadata": metadata})

    add(ada, "Spins", "Physical Review B")
    add(ada, "Holes", "Physical Review B")
    add(ada, "Cavities", "Physical Review Letters")
    add(ada, "Notes", None)
    add(bob, "Bob's", "Nature Physics")

    def titles(**params: Any) -> list[str]:  # noqa: ANN401
        return sorted(i["title"] for i in ada.get("/api/items", params=params).json())

    # Any case; one of several.
    assert titles(journal=["physical review b"]) == ["Holes", "Spins"]
    assert titles(journal=["Physical Review B", "Physical Review Letters"]) == [
        "Cavities",
        "Holes",
        "Spins",
    ]
    # A smart collection with the rule.
    smart = ada.post(
        "/api/collections",
        json={"name": "PRL", "rules": {"journals": ["Physical Review Letters"]}},
    ).json()
    assert titles(collection=smart["id"]) == ["Cavities"]

    # The journals to choose from: one's own (not bob's), the most papers
    # first; by words in them.
    assert ada.get("/api/journals").json() == [
        {"name": "Physical Review B", "papers": 2},
        {"name": "Physical Review Letters", "papers": 1},
    ]
    assert [
        j["name"] for j in ada.get("/api/journals", params={"q": "lett"}).json()
    ] == ["Physical Review Letters"]
