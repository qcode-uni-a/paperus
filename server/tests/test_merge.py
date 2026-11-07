"""Merging duplicates: what moves, what is there already, what stays behind
and why, and what may be dropped from the paper that stays."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import merge
from paperus.access import Access
from paperus.models import Item, User, Version
from tests.people import Person, group


def pdf(text: str) -> bytes:
    return b"%PDF-1.7\n" + text.encode() * 500 + b"\n%%EOF\n"


def paper(
    person: Person, title: str, doi: str | None = None, library: str | None = None
) -> dict[str, Any]:
    response = person.post(
        "/api/items",
        json={
            "metadata": {"title": title},
            "identifiers": [{"scheme": "doi", "value": doi}] if doi else [],
            "library_id": library,
        },
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def upload(person: Person, item: dict[str, Any], name: str, data: bytes) -> str:
    response = person.post(
        f"/api/items/{item['id']}/files",
        files={"upload": (name, data, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    file_id: str = response.json()["id"]
    return file_id


def tag(person: Person, item: dict[str, Any], name: str, library: str) -> str:
    response = person.post(
        f"/api/items/{item['id']}/tags", json={"name": name, "library_id": library}
    )
    assert response.status_code == 201, response.text
    return next(t["id"] for t in response.json() if t["name"] == name)


def collect(person: Person, name: str, library: str, *items: dict[str, Any]) -> str:
    created = person.post(
        "/api/collections", json={"name": name, "library_id": library}
    )
    assert created.status_code == 201, created.text
    collection: str = created.json()["id"]
    added = person.post(
        f"/api/collections/{collection}/items",
        json={"item_ids": [i["id"] for i in items]},
    )
    assert added.status_code == 200, added.text
    return collection


def steps(person: Person, source: dict[str, Any], target: dict[str, Any]) -> set[Any]:
    response = person.get(
        f"/api/items/{source['id']}/merge-preview", params={"into": target["id"]}
    )
    assert response.status_code == 200, response.text
    return {
        (s["kind"], s["name"], s["action"], s["reason"])
        for s in response.json()["steps"]
    }


def own(person: Person) -> str:
    library: str = person.libraries()["Me"]["id"]
    return library


def test_the_same_version_twice(client: TestClient, db: Session) -> None:
    root, ada = Person(client, db, "root", admin=True), Person(client, db, "ada")
    bob = Person(client, db, "bob")
    chair = group(root, "Chair", bob)
    # Ada's own copy and the Chair's, added before she joined: one paper twice.
    away = paper(ada, "Radar", "10.1234/radar")
    keep = paper(bob, "Radar gaps", "10.1234/radar", chair["library_id"])
    bob.put(f"/api/groups/{chair['id']}/members/{ada.id}", json={"role": "member"})
    upload(ada, away, "annotated.pdf", pdf("annotated"))
    upload(ada, away, "radar.pdf", pdf("radar"))
    upload(bob, keep, "radar.pdf", pdf("radar"))
    # Found by the shared DOI.
    found = ada.get(f"/api/items/{away['id']}/duplicates").json()
    assert [i["id"] for i in found] == [keep["id"]]
    assert steps(ada, away, keep) == {
        ("version", "Version: doi 10.1234/radar", "already", "the same version"),
        ("file", "annotated.pdf", "move", None),
        ("file", "radar.pdf", "already", "the same file"),
    }
    merged = ada.post(f"/api/items/{away['id']}/merge", json={"into": keep["id"]})
    assert merged.status_code == 200, merged.text
    [version] = merged.json()["item"]["versions"]
    roles = {f["filename"]: f["role"] for f in version["files"]}
    # The paper that stays keeps its main file.
    assert roles == {"radar.pdf": "main", "annotated.pdf": "other"}


def test_pinned_versions(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    away = paper(ada, "Radar (preprint)", "10.1234/preprint")
    keep = paper(ada, "Radar", "10.1234/radar")
    for item in (away, keep):
        version = db.scalar(select(Version).where(Version.item_id == item["id"]))
        assert version is not None
        version.pinned = True
    db.commit()
    merged = ada.post(f"/api/items/{away['id']}/merge", json={"into": keep["id"]})
    assert merged.status_code == 200, merged.text
    pins = {
        v["identifiers"][0]["value"]: v["pinned"]
        for v in merged.json()["item"]["versions"]
    }
    # Only one stays pinned: the one that was.
    assert pins == {"10.1234/radar": True, "10.1234/preprint": False}


@pytest.fixture
def chair(client: TestClient, db: Session) -> dict[str, Any]:
    """Ada runs the Chair (and the Lab); Bob reads the Chair; Carl is a
    member of both."""
    root = Person(client, db, "root", admin=True)
    ada, bob, carl = (Person(client, db, n) for n in ("ada", "bob", "carl"))
    chair, lab = group(root, "Chair", ada), group(root, "Lab", ada)
    for person, role in ((bob, "reader"), (carl, "member")):
        ada.put(f"/api/groups/{chair['id']}/members/{person.id}", json={"role": role})
    ada.put(f"/api/groups/{lab['id']}/members/{carl.id}", json={"role": "member"})
    return {
        **{"ada": ada, "bob": bob, "carl": carl, "chair": chair, "lab": lab},
        **{"client": client, "db": db},
    }


def test_what_stays_for_a_reader(chair: dict[str, Any]) -> None:
    ada = chair["ada"]
    library = chair["chair"]["library_id"]
    shared = paper(ada, "Radar", "10.1234/radar", library)
    upload(ada, shared, "radar.pdf", pdf("radar"))
    group_tag = tag(ada, shared, "weather", library)
    shelf = collect(ada, "Shelf", library, shared)
    # Dan had the paper before he joined the Chair as a reader.
    bob = Person(chair["client"], chair["db"], "dan")
    copy = paper(bob, "Radar, my copy", "10.1234/radar")
    ada.put(
        f"/api/groups/{chair['chair']['id']}/members/{bob.id}", json={"role": "reader"}
    )
    upload(bob, copy, "notes.pdf", pdf("notes"))
    tag(bob, copy, "weather", library)  # the group's tag, on his own paper
    tag(bob, copy, "mine", own(bob))
    tag(bob, shared, "mine", own(bob))
    assert steps(bob, copy, shared) == {
        ("version", "Version: doi 10.1234/radar", "already", "the same version"),
        ("file", "notes.pdf", "stays", "you may not change the other paper"),
        ("tag", "weather", "already", None),
        ("tag", "mine", "already", None),
    }
    # A reader may not drop the group's tag, collection or file from it.
    file_id = ada.get(f"/api/items/{shared['id']}").json()["versions"][0]["files"][0][
        "id"
    ]
    for thing, reason in (
        (group_tag, "you may not change this paper's tags"),
        (shelf, "you may not change this collection"),
        (file_id, "you may not change the other paper"),
    ):
        response = bob.post(
            f"/api/items/{copy['id']}/merge",
            json={"into": shared["id"], "drop": [thing]},
        )
        assert (response.status_code, response.json()["detail"]) == (409, reason)


def test_a_group_tag_stays_on_a_paper_one_reads(chair: dict[str, Any]) -> None:
    ada, bob = chair["ada"], chair["bob"]
    library = chair["chair"]["library_id"]
    shared = paper(ada, "Radar", None, library)
    tag(ada, paper(ada, "Rain", None, library), "weather", library)
    copy = paper(bob, "Radar, my copy")
    tag(bob, copy, "weather", library)
    reason = "a group's tags go only on papers you may change"
    assert ("tag", "weather", "stays", reason) in steps(bob, copy, shared)


def test_what_others_cannot_see_and_group_collections(chair: dict[str, Any]) -> None:
    ada, carl = chair["ada"], chair["carl"]
    chair_library = chair["chair"]["library_id"]
    lab_library = chair["lab"]["library_id"]
    keep = paper(ada, "Radar", None, chair_library)
    away = paper(carl, "Radar (Lab)", None, lab_library)
    # Ada's private tag and collection: Carl does not see them.
    tag(ada, away, "ada's", own(ada))
    collect(ada, "Ada's shelf", own(ada), away)
    # The Lab's collection holds only the Lab's papers; Carl's own holds both.
    collect(carl, "Lab shelf", lab_library, away)
    collect(carl, "Carl's shelf", own(carl), away, keep)
    assert steps(carl, away, keep) == {
        ("version", "Version without identifier", "move", None),
        (
            "collection",
            "Lab shelf",
            "stays",
            "a group's collection takes only that group's papers",
        ),
        ("collection", "Carl's shelf", "already", None),
    }
    # Dropping the paper from one of its collections when merging.
    kept_shelf = collect(carl, "Chair shelf", chair_library, keep)
    merged = carl.post(
        f"/api/items/{away['id']}/merge",
        json={"into": keep["id"], "drop": [kept_shelf]},
    )
    assert merged.status_code == 200, merged.text
    assert kept_shelf not in merged.json()["item"]["collection_ids"]


def test_no_merge_into_the_trash(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    away, keep = paper(ada, "A"), paper(ada, "B")
    assert ada.delete(f"/api/items/{keep['id']}").status_code == 204
    user = db.get(User, uuid.UUID(ada.id))
    source = db.get(Item, uuid.UUID(away["id"]))
    target = db.get(Item, uuid.UUID(keep["id"]))
    assert user is not None and source is not None and target is not None
    with pytest.raises(merge.CannotMerge, match="in the trash"):
        merge.plan_merge(Access.of(db, user), source, target)


def test_leave_and_drop(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    away, keep = paper(ada, "Radar"), paper(ada, "Radar gaps")
    scan = upload(ada, away, "scan.pdf", pdf("scan"))
    old = upload(ada, keep, "old.pdf", pdf("old"))
    tag(ada, away, "radar", own(ada))
    stale = tag(ada, keep, "stale", own(ada))
    shelf = collect(ada, "Shelf", own(ada), away)
    moved = ada.note("Read it.", items=[away["id"]])
    left = ada.note("Wrong paper.", items=[away["id"]])
    url = f"/api/items/{away['id']}/merge"
    for body, reason in (
        ({"into": away["id"]}, "a paper cannot be merged into itself"),
        (
            {"into": keep["id"], "drop": [str(uuid.uuid4())]},
            "not a tag, collection or file of the other paper",
        ),
    ):
        response = ada.post(url, json=body)
        assert (response.status_code, response.json()["detail"]) == (409, reason)
    response = ada.post(
        url,
        json={"into": keep["id"], "leave": [scan, left["id"]], "drop": [stale, old]},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    actions = {(s["kind"], s["name"]): s["action"] for s in result["steps"]}
    assert actions == {
        ("version", "Version without identifier"): "move",
        ("file", "scan.pdf"): "stays",
        ("tag", "radar"): "move",
        ("collection", "Shelf"): "move",
        ("note", "Read it."): "move",
        ("note", "Wrong paper."): "stays",
    }
    item = result["item"]
    assert [t["name"] for t in item["tags"]] == ["radar"]
    assert item["collection_ids"] == [shelf]
    # The file left behind and the dropped one are in the trash.
    assert item["files"] == []
    notes = ada.get(f"/api/notes?item={keep['id']}").json()
    assert [n["id"] for n in notes] == [moved["id"]]
