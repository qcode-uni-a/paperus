"""Favourites (starred papers) and collections pinned to the sidebar."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.people import Person, group


def test_favourites_are_per_person(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    shared = ada.add("Shared paper", chair["library_id"])
    ada.add("Ada's other paper")

    # Readers may star too: it changes only their own view.
    assert bob.put(f"/api/items/{shared['id']}/favourite").status_code == 204
    assert bob.put(f"/api/items/{shared['id']}/favourite").status_code == 204
    assert bob.get(f"/api/items/{shared['id']}").json()["favourite"] is True
    assert ada.get(f"/api/items/{shared['id']}").json()["favourite"] is False
    assert [i["title"] for i in bob.get("/api/items?favourite=true").json()] == [
        "Shared paper"
    ]
    assert ada.get("/api/items?favourite=true").json() == []
    assert bob.delete(f"/api/items/{shared['id']}/favourite").status_code == 204
    assert bob.get("/api/items?favourite=true").json() == []
    # Only papers one can see.
    private = ada.add("Private")
    assert bob.put(f"/api/items/{private['id']}/favourite").status_code == 404


def test_pinned_collections(client: TestClient, db: Session) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    thesis = ada.post("/api/collections", json={"name": "Thesis"}).json()
    ada.post("/api/collections", json={"name": "Other"})
    assert ada.put(f"/api/collections/{thesis['id']}/pin").status_code == 204
    pinned = {c["name"]: c["pinned"] for c in ada.get("/api/collections").json()}
    assert pinned == {"Other": False, "Thesis": True}
    assert bob.put(f"/api/collections/{thesis['id']}/pin").status_code == 404
    assert ada.delete(f"/api/collections/{thesis['id']}/pin").status_code == 204
    assert not any(c["pinned"] for c in ada.get("/api/collections").json())
