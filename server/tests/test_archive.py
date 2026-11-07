"""The archive: papers kept for good, but left out of lists, search and
Manage unless asked for."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.storage import BlobStore
from tests.people import Person, group
from tests.test_search import PAPER, process, upload


def titles(person: Person, **params: bool | str | list[str]) -> list[str]:
    response = person.get("/api/items", params=params)
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()]


def test_archived_papers_are_left_out(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    ada = Person(client, db, "ada")
    old = ada.post("/api/items", json={"metadata": {"title": "Old drought study"}})
    old_id = old.json()["id"]
    ada.post("/api/items", json={"metadata": {"title": "Current work"}})
    process(db, blobs, upload(client, old_id, PAPER))
    assert ada.get("/api/manage/counts").json()["missing"] == 1

    assert ada.put(f"/api/items/{old_id}/archive").status_code == 204
    assert titles(ada) == ["Current work"]
    assert titles(ada, archived=True) == ["Old drought study"]
    # Asked for by id (a note's linked papers): still there.
    assert titles(ada, id=[old_id]) == ["Old drought study"]
    detail = ada.get(f"/api/items/{old_id}").json()
    assert detail["archived_at"] is not None

    found = ada.get("/api/search", params={"q": "SPEI"}).json()
    assert found == []
    found = ada.get("/api/search", params={"q": "SPEI", "archived": True}).json()
    assert [p["item_title"] for p in found] == ["Old drought study"]
    # Within the paper itself, it is searched.
    within = ada.get("/api/search", params={"q": "SPEI", "item": old_id}).json()
    assert len(within) == 1

    assert ada.delete(f"/api/items/{old_id}/archive").status_code == 204
    assert titles(ada) == ["Current work", "Old drought study"]


def test_missing_and_readers(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    shared = ada.post(
        "/api/items",
        json={"metadata": {"title": "Group paper"}, "library_id": chair["library_id"]},
    ).json()["id"]
    assert ada.get("/api/manage/counts").json()["missing"] == 1
    # Readers may not archive the group's papers.
    assert bob.put(f"/api/items/{shared}/archive").status_code == 403
    assert ada.put(f"/api/items/{shared}/archive").status_code == 204
    # Archived for everyone; not missing a PDF any more.
    assert titles(bob) == []
    assert ada.get("/api/manage/counts").json()["missing"] == 0
    # In the trash, an archived paper is listed there as usual.
    ada.delete(f"/api/items/{shared}")
    assert titles(ada, trashed=True) == ["Group paper"]
