"""Syncing: ``/api/changes`` (``paperus.api.sync``)."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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
    assert ids(changes(ada)["annotations"]) == [mark]

    # Nothing since.
    since = first["change"]
    quiet = changes(bob, since)
    assert {k: v for k, v in quiet.items() if v} == {
        "change": since,
        "libraries": first["libraries"],
    }

    # Shared, then a tag deleted: changes and removals.
    ada.put(f"/api/items/{paper['id']}/annotation-sharing", {"shared": True})
    assert ada.delete(f"/api/tags/{tag.json()['id']}").status_code == 204
    later = changes(bob, since)
    assert ids(later["annotations"]) == [mark]
    assert later["annotations"][0]["mine"] is False
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
