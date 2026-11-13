"""One change to many papers (``POST /api/items/bulk``)."""

from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.api import bulk as bulk_api
from tests.people import Person, group


def bulk(person: Person, ids: list[str], **action: str) -> dict[str, Any]:
    response = person.post("/api/items/bulk", json={"item_ids": ids, "action": action})
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def test_trash_archive_star_and_back(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    ids = [ada.add(t)["id"] for t in ("Rain", "Snow", "Hail")]

    assert bulk(ada, ids[:2], kind="archive")["done"] == ids[:2]
    assert ada.titles() == ["Hail"]
    assert ada.titles(archived="true") == ["Rain", "Snow"]
    bulk(ada, ids[:2], kind="unarchive")

    bulk(ada, ids, kind="star")
    assert ada.titles(favourite="true") == ["Hail", "Rain", "Snow"]
    bulk(ada, ids[1:], kind="unstar")
    assert ada.titles(favourite="true") == ["Rain"]

    bulk(ada, [ids[0], ids[1], ids[0]], kind="trash")  # twice: once
    assert ada.titles() == ["Hail"]
    assert ada.titles(trashed="true") == ["Rain", "Snow"]
    assert bulk(ada, ids[:2], kind="restore")["skipped"] == []
    assert ada.titles() == ["Hail", "Rain", "Snow"]


def test_tags_and_collections(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    ids = [ada.add(t)["id"] for t in ("Rain", "Snow")]

    assert bulk(ada, ids, kind="tag", name="weather")["done"] == ids
    tag = ada.get("/api/tags").json()[0]
    assert ada.titles(tag=tag["id"]) == ["Rain", "Snow"]
    bulk(ada, ids[:1], kind="untag", tag_id=tag["id"])
    assert ada.titles(tag=tag["id"]) == ["Snow"]

    shelf = ada.post("/api/collections", json={"name": "Shelf"}).json()
    bulk(ada, ids, kind="collect", collection_id=shelf["id"])
    assert ada.titles(collection=shelf["id"]) == ["Rain", "Snow"]
    bulk(ada, ids[1:], kind="uncollect", collection_id=shelf["id"])
    assert ada.titles(collection=shelf["id"]) == ["Rain"]

    # A smart collection takes no papers by hand.
    smart = ada.post(
        "/api/collections", json={"name": "Smart", "rules": {"match": "all"}}
    )
    response = ada.post(
        "/api/items/bulk",
        json={
            "item_ids": ids,
            "action": {"kind": "collect", "collection_id": smart.json()["id"]},
        },
    )
    assert response.status_code == 409


def matching(person: Person, filters: dict[str, Any], **action: str) -> httpx2.Response:
    return person.post("/api/items/bulk", json={"matching": filters, "action": action})


def test_every_paper_a_filter_matches(client: TestClient, db: Session) -> None:
    """ "Select all": the list's filters instead of the ids, however many."""
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    ids = [ada.add(t)["id"] for t in ("Rain on Mars", "Rain in Spain", "Snow")]
    bob.add("Rain for Bob")

    result = matching(ada, {"title": "rain"}, kind="tag", name="wet").json()
    assert sorted(result["done"]) == sorted(ids[:2])
    tag = ada.get("/api/tags").json()[0]
    assert ada.titles(tag=tag["id"]) == ["Rain in Spain", "Rain on Mars"]
    # The whole library (bob's paper is not ada's to see).
    assert matching(ada, {}, kind="archive").json()["done"] == ids
    assert ada.titles() == []
    # The archive, as its list shows it.
    assert matching(ada, {"archived": True}, kind="unarchive").json()["done"] == ids
    # Someone else's tag answers as if it did not exist.
    assert matching(bob, {"tag": [tag["id"]]}, kind="star").status_code == 404
    # One way or the other, not both or neither.
    for body in ({"item_ids": ids, "matching": {}}, {}):
        response = ada.post(
            "/api/items/bulk", json={**body, "action": {"kind": "star"}}
        )
        assert response.status_code == 422


def test_too_many_matching(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ada = Person(client, db, "ada")
    for t in ("Rain", "Snow"):
        ada.add(t)
    monkeypatch.setattr(bulk_api, "MAX_MATCHING", 1)
    response = matching(ada, {}, kind="star")
    assert response.status_code == 413
    assert ada.titles(favourite="true") == []


def test_papers_one_may_not_change_are_skipped(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", json={"role": "reader"})
    shared = ada.add("Group paper", lab["library_id"])["id"]
    own = bob.add("Bob's paper")["id"]
    hidden = ada.add("Ada's own")["id"]

    result = bulk(bob, [own, shared, hidden], kind="trash")
    assert result["done"] == [own]
    assert {s["item_id"]: s["reason"] for s in result["skipped"]} == {
        shared: "readers cannot change this item",
        hidden: "item not found",
    }
    assert bob.titles(trashed="true") == ["Bob's paper"]

    # A reader's tag on the group's paper is a private one; theirs.
    assert bulk(bob, [shared], kind="tag", name="to read")["done"] == [shared]
    # A group's collection holds only the group's papers.
    shelf = ada.post(
        "/api/collections", json={"name": "Shelf", "library_id": lab["library_id"]}
    ).json()
    result = bulk(ada, [shared, hidden], kind="collect", collection_id=shelf["id"])
    assert result["done"] == [shared]
    assert result["skipped"][0]["reason"] == (
        "a group's collection holds only the group's papers"
    )


def test_give_papers_to_a_group(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", json={"role": "member"})
    ids = [ada.add(t)["id"] for t in ("Rain", "Snow")]

    assert bulk(ada, ids, kind="owner", library_id=lab["library_id"])["done"] == ids
    assert bob.titles() == ["Rain", "Snow"]
    # Only to an owner one may add to.
    response = bob.post(
        "/api/items/bulk",
        json={
            "item_ids": ids,
            "action": {"kind": "owner", "library_id": ada.libraries()["Me"]["id"]},
        },
    )
    assert response.status_code == 404


def test_a_readers_tags(client: TestClient, db: Session) -> None:
    """A reader may not use or take off the group's tags on its papers."""
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", json={"role": "reader"})
    shared = ada.add("Group paper", lab["library_id"])["id"]
    bulk(ada, [shared], kind="tag", name="optics")
    [optics] = ada.get("/api/tags").json()

    result = bulk(
        bob, [shared], kind="tag", name="optics", library_id=lab["library_id"]
    )
    assert result["skipped"][0]["reason"] == "you may not change this item's tags"
    result = bulk(bob, [shared], kind="untag", tag_id=optics["id"])
    assert result["skipped"][0]["reason"] == "you may not change this item's tags"
    # Nor someone else's tags at all.
    response = bob.post(
        "/api/items/bulk",
        json={
            "item_ids": [shared],
            "action": {
                "kind": "tag",
                "name": "x",
                "library_id": ada.libraries()["Me"]["id"],
            },
        },
    )
    assert response.status_code == 404
