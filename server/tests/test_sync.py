"""Syncing: ``/api/changes`` (``paperus.api.sync``)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from paperus import changes as changes_module
from paperus.models import Removal
from tests.people import Person, group

PDF = b"%PDF-1.7\n%%EOF\n"
MARK = {
    "kind": "note",
    "page_index": 0,
    "position": {"rects": [[10, 10, 20, 20]]},
    "color": "#ffd400",
}


def changes(
    person: Person, since: int = 0, library: list[str] | None = None
) -> dict[str, Any]:
    params: dict[str, str | list[str]] = {"since": str(since)}
    if library is not None:
        params["library"] = library
    response = person.get("/api/changes", params=params)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def ids(records: list[dict[str, Any]]) -> list[str]:
    return [record["id"] for record in records]


def test_everything_since_and_what_is_gone(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", json={"role": "reader"})
    mine = ada.add("Ada's own")
    paper = ada.add("The lab's", lab["library_id"])
    file = ada.post(
        f"/api/items/{paper['id']}/files",
        files={"upload": ("p.pdf", PDF, "application/pdf")},
    ).json()["id"]
    note = ada.note("# Seminar\n\nOn the lab's paper", lab["library_id"], [paper["id"]])
    tag = ada.post("/api/tags", {"name": "optics", "library_id": lab["library_id"]})
    shelf = ada.post(
        "/api/collections", {"name": "Shelf", "library_id": lab["library_id"]}
    ).json()
    mark = ada.post(f"/api/files/{file}/annotations", MARK).json()["id"]
    place = {"file_id": file, "page": 1, "top": 5.0, "left": None}
    bob.put(f"/api/items/{paper['id']}/reading", place)

    # From 0: all Bob sees; Ada's annotation is hers until she shares it.
    first = changes(bob)
    assert len(first["libraries"]) == 2 and lab["library_id"] in first["libraries"]
    assert ids(first["items"]) == [paper["id"]]
    assert ids(first["notes"]) == [note["id"]]
    assert first["notes"][0]["text"].startswith("# Seminar")
    assert ids(first["tags"]) == [tag.json()["id"]]
    assert ids(first["collections"]) == [shelf["id"]]
    assert first["annotations"] == [] and first["removed"] == []
    assert first["views"] == [
        {
            "item_id": paper["id"],
            "viewed_at": first["views"][0]["viewed_at"],
            "reading": place,
        }
    ]
    assert ids(changes(ada)["items"]) == [mine["id"], paper["id"]]
    assert first["favourites"] == []
    bob.put(f"/api/items/{paper['id']}/favourite")
    assert changes(bob)["favourites"] == [paper["id"]]
    assert ids(changes(ada)["annotations"]) == [mark]

    # Nothing since.
    since = first["change"]
    quiet = changes(bob, since)
    assert {k: v for k, v in quiet.items() if v} == {
        "change": since,
        "libraries": first["libraries"],
        "favourites": [paper["id"]],
    }

    # Shared, then a tag deleted: changes and removals.
    ada.put(f"/api/items/{paper['id']}/annotation-sharing", {"shared": True})
    assert ada.delete(f"/api/tags/{tag.json()['id']}").status_code == 204
    later = changes(bob, since)
    assert ids(later["annotations"]) == [mark]
    assert later["annotations"][0]["mine"] is False
    assert later["annotations"][0]["item_id"] == paper["id"]
    assert later["removed"] == [{"id": tag.json()["id"], "kind": "tag"}]

    # No longer shared: gone for Bob, changed for Ada (she keeps it).
    since = later["change"]
    ada.put(f"/api/items/{paper['id']}/annotation-sharing", {"shared": False})
    gone = {"id": mark, "kind": "annotation"}
    assert changes(bob, since)["removed"] == [gone]
    assert changes(bob, since)["annotations"] == []
    for_ada = changes(ada, since)
    assert for_ada["removed"] == [gone] and ids(for_ada["annotations"]) == [mark]

    # One library only (one Bob may read since): others are left out.
    only = changes(bob, 0, library=[lab["library_id"], mine["library_id"]])
    assert only["libraries"] == [lab["library_id"]]
    assert ids(only["items"]) == [paper["id"]]


def test_ids_made_on_a_device(client: TestClient, db: Session) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    paper = ada.add("Read offline")
    file = ada.post(
        f"/api/items/{paper['id']}/files",
        files={"upload": ("p.pdf", PDF, "application/pdf")},
    ).json()["id"]
    creates = {
        "/api/notes": {"text": "# Written on the train"},
        "/api/tags": {"name": "train"},
        "/api/collections": {"name": "Commute"},
        f"/api/files/{file}/annotations": MARK,
    }
    for url, body in creates.items():
        made = str(db.scalar(text("SELECT uuidv7()")))
        first = ada.post(url, {"id": made, **body})
        assert first.status_code == 201, (url, first.text)
        assert first.json()["id"] == made
        # Sent again (the answer was lost): the same record, not a second.
        again = ada.post(url, {"id": made, **body})
        assert (again.status_code, again.json()["id"]) == (201, made)
        # Someone who does not see it cannot take its ID.
        assert bob.post(url, {"id": made, **body}).status_code in (404, 409)
    assert len(ada.get("/api/notes").json()) == 1
    assert [t["name"] for t in ada.get("/api/tags").json()] == ["train"]
    assert len(ada.get(f"/api/files/{file}/annotations").json()["annotations"]) == 1

    # Only UUIDv7s, as the server makes them.
    old_style = ada.post("/api/tags", {"id": str(uuid.uuid4()), "name": "v4"})
    assert old_style.status_code == 422


def test_offline_too_long(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    tag = ada.post("/api/tags", {"name": "old"}).json()["id"]
    since = changes(ada)["change"]
    ada.delete(f"/api/tags/{tag}")
    later = changes(ada, since)
    assert later["removed"] == [{"id": tag, "kind": "tag"}]

    # A year on, the removal is forgotten: syncing from before it would miss
    # it, so the device is told to sync anew (after sending its changes).
    now = datetime.now(UTC)
    assert changes_module.forget_removals(db, now) == 0
    db.execute(update(Removal).values(removed_at=now - timedelta(days=366)))
    assert changes_module.forget_removals(db, now) == 1
    assert changes_module.forget_removals(db, now) == 0
    response = ada.get("/api/changes", params={"since": str(since)})
    assert response.status_code == 410
    assert changes(ada, later["change"])["removed"] == []
    assert ids(changes(ada)["tags"]) == []


def test_queued_edits_do_not_overwrite(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Edited twice")
    file = ada.post(
        f"/api/items/{paper['id']}/files",
        files={"upload": ("p.pdf", PDF, "application/pdf")},
    ).json()["id"]
    made = {
        "/api/tags": ada.post("/api/tags", {"name": "draft"}).json(),
        "/api/collections": ada.post("/api/collections", {"name": "Draft"}).json(),
        "/api/annotations": ada.post(f"/api/files/{file}/annotations", MARK).json(),
    }
    edits = {
        "/api/tags": ({"name": "second"}, {"name": "third"}),
        "/api/collections": ({"name": "Second"}, {"name": "Third"}),
        "/api/annotations": ({"comment": "second"}, {"comment": "third"}),
    }
    for kind, record in made.items():
        url = f"{kind}/{record['id']}"
        read = f'"{record["change"]}"'
        first, queued = edits[kind]
        # Changed elsewhere (no If-Match: as the website does).
        changed = ada.client.patch(url, json=first, headers=ada.headers)
        assert changed.status_code == 200, changed.text
        # The device's edit from the old version: refused, nothing lost.
        stale = ada.client.patch(
            url, json=queued, headers={**ada.headers, "If-Match": read}
        )
        assert stale.status_code == 412, (kind, stale.text)
        current = f'"{changed.json()["change"]}"'
        assert (
            ada.client.patch(
                url, json=queued, headers={**ada.headers, "If-Match": current}
            ).status_code
            == 200
        )
        broken = ada.client.patch(
            url, json=queued, headers={**ada.headers, "If-Match": "yesterday"}
        )
        assert broken.status_code == 412
