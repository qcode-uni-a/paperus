"""Notes: titles, the edit history, conflicts, trash and export."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from paperus import notes
from paperus.models import Note, NoteChunk
from tests.people import Person, group


def save(person: Person, note_id: str, text: str, etag: str) -> tuple[int, str]:
    response = person.patch(
        f"/api/notes/{note_id}", json={"text": text}, headers={"If-Match": etag}
    )
    return response.status_code, response.headers.get("ETag", "")


def test_title_excerpt_and_markdown(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    note = ada.note("\n## *Reading* group, week 3\n\nWe read **two** papers.\n")
    assert note["title"] == "Reading group, week 3"
    assert note["excerpt"] == "We read two papers."
    assert note["text"].startswith("\n## *Reading*")
    download = ada.get(f"/api/notes/{note['id']}/markdown")
    assert download.text == note["text"]
    assert "Reading-group-week-3.md" in download.headers["content-disposition"]
    # Split into passages for search.
    assert db.query(NoteChunk).filter_by(note_id=note["id"]).count() == 1


def test_history_and_conflicts(client: TestClient, db: Session) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    root = Person(client, db, "root", admin=True)
    chair = root.post(
        "/api/groups", json={"name": "Chair", "parent_id": None, "admin_id": ada.id}
    ).json()
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "member"})
    note = ada.note("First", chair["library_id"])
    url = f"/api/notes/{note['id']}"
    etag = ada.get(url).headers["ETag"]

    # Saves by the same person in one session: no history entry.
    status, etag = save(ada, note["id"], "Second", etag)
    status, etag = save(ada, note["id"], "Third", etag)
    assert status == 200 and ada.get(f"{url}/history").json() == []

    # Someone else saving from an old ETag is refused.
    assert save(bob, note["id"], "Bob's", '"1"')[0] == 412
    assert save(bob, note["id"], "Bob's", "")[0] == 412
    bob_etag = bob.get(url).headers["ETag"]
    status, _ = save(bob, note["id"], "Bob's", bob_etag)
    assert status == 200
    [kept] = ada.get(f"{url}/history").json()
    assert (kept["text"], kept["written_by"]) == ("Third", "ada")

    # Ada again later: Bob's text is kept too.
    db.execute(
        update(Note)
        .where(Note.id == note["id"])
        .values(text_changed_at=Note.text_changed_at - timedelta(hours=1))
    )
    db.commit()
    save(ada, note["id"], "Ada's again", ada.get(url).headers["ETag"])
    history = ada.get(f"{url}/history").json()
    assert [(h["text"], h["written_by"]) for h in history] == [
        ("Bob's", "bob"),
        ("Third", "ada"),
    ]
    assert ada.get(url).json()["changed_by"] == "ada"


def test_trash_and_lists(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Radar")
    note = ada.note("On radar", items=[paper["id"]])
    standalone = ada.note("Ideas")
    titles = [n["title"] for n in ada.get("/api/notes").json()]
    assert titles == ["Ideas", "On radar"]
    assert [n["title"] for n in ada.get(f"/api/notes?item={paper['id']}").json()] == [
        "On radar"
    ]
    ada.delete(f"/api/notes/{standalone['id']}")
    assert [n["title"] for n in ada.get("/api/notes").json()] == ["On radar"]
    assert [n["title"] for n in ada.get("/api/notes?trashed=true").json()] == ["Ideas"]
    response = ada.patch(
        f"/api/notes/{standalone['id']}",
        json={"text": "x"},
        headers={"If-Match": '"0"'},
    )
    assert response.status_code == 409
    # A trashed paper's link is hidden, the note stays.
    ada.delete(f"/api/items/{paper['id']}")
    assert ada.get(f"/api/notes/{note['id']}").json()["items"] == []


def test_filing_and_linking_do_not_conflict_with_editing(
    client: TestClient, db: Session
) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Radar")
    note = ada.note("Draft")
    url = f"/api/notes/{note['id']}"
    etag = ada.get(url).headers["ETag"]
    changed_at = ada.get(url).json()["changed_at"]
    # Filed and linked meanwhile (by the same person, in another tab).
    shelf = ada.post("/api/collections", json={"name": "Shelf"}).json()
    ada.post(f"/api/collections/{shelf['id']}/notes", json={"note_ids": [note["id"]]})
    ada.put(f"{url}/items/{paper['id']}", json={})
    assert ada.get(url).json()["changed_at"] == changed_at  # lists keep their order
    # The text is still the version the editor has: saving works.
    assert save(ada, note["id"], "Draft, longer", etag)[0] == 200


def test_links_to_trashed_papers_can_be_removed(
    client: TestClient, db: Session
) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Radar")
    note = ada.note("About radar", items=[paper["id"]])
    ada.delete(f"/api/items/{paper['id']}")
    response = ada.delete(f"/api/notes/{note['id']}/items/{paper['id']}")
    assert response.status_code == 200
    ada.post(f"/api/items/{paper['id']}/restore")
    assert ada.get(f"/api/notes/{note['id']}").json()["items"] == []


def test_owners_collections_and_pages(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, eve = Person(client, db, "ada"), Person(client, db, "eve")
    chair = group(root, "Chair", ada)
    paper = ada.add("Radar")
    note = ada.note("# Minutes", items=[paper["id"]])
    url = f"/api/notes/{note['id']}"

    # The same paper again: its page changes, no second link.
    linked = ada.put(f"{url}/items/{paper['id']}", json={"page": 4}).json()
    assert linked["items"] == [{"item_id": paper["id"], "title": "Radar", "page": 4}]

    # A group's collection holds only the group's notes.
    shelf = ada.post(
        "/api/collections", json={"name": "Shelf", "library_id": chair["library_id"]}
    ).json()
    inner = ada.post(
        "/api/collections", json={"name": "Inner", "parent_id": shelf["id"]}
    ).json()
    refused = ada.post(
        "/api/notes", json={"text": "# Mine", "collection_id": shelf["id"]}
    )
    assert refused.status_code == 409
    mine = ada.post("/api/collections", json={"name": "Mine"}).json()
    filed = ada.post("/api/notes", json={"text": "# Mine", "collection_id": mine["id"]})
    assert filed.json()["collection_ids"] == [mine["id"]]
    ada.post(f"/api/collections/{inner['id']}/notes", json={"note_ids": [note["id"]]})
    assert ada.get(url).json()["collection_ids"] == []  # skipped
    # Given to the group, it may go in; twice is once.
    owner = ada.put(f"{url}/owner", json={"library_id": chair["library_id"]})
    assert owner.status_code == 200, owner.text
    for _ in range(2):
        ada.post(
            f"/api/collections/{inner['id']}/notes", json={"note_ids": [note["id"]]}
        )
    assert ada.get(url).json()["collection_ids"] == [inner["id"]]
    nested = ada.get("/api/notes", params={"collection": shelf["id"]}).json()
    assert [n["id"] for n in nested] == [note["id"]]
    only_shelf = {"collection": shelf["id"], "nested": False}
    assert ada.get("/api/notes", params=only_shelf).json() == []
    # Back to Ada alone: the group's collection lets it go.
    ada.put(f"{url}/owner", json={"library_id": ada.libraries()["Me"]["id"]})
    assert ada.get(url).json()["collection_ids"] == []
    ada.put(f"{url}/owner", json={"library_id": chair["library_id"]})
    ada.post(f"/api/collections/{inner['id']}/notes", json={"note_ids": [note["id"]]})
    removed = ada.delete(f"/api/collections/{inner['id']}/notes/{note['id']}")
    assert removed.status_code == 204
    assert ada.get(url).json()["collection_ids"] == []

    # Trashed and restored.
    ada.delete(url)
    restored = ada.post(f"{url}/restore")
    assert restored.status_code == 200 and restored.json()["deleted_at"] is None

    # Others: not found, as if there were no such note or paper.
    assert eve.get(url).status_code == 404
    assert eve.get(f"/api/notes/{uuid.uuid4()}").status_code == 404
    about_ada = eve.post("/api/notes", json={"items": [{"item_id": paper["id"]}]})
    assert about_ada.status_code == 404
    # Saving needs the version the editor started from.
    assert ada.patch(url, json={"text": "x"}).status_code == 428


def test_saving_the_same_text_changes_nothing(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    note = ada.note("")
    assert note["title"] == ""
    url = f"/api/notes/{note['id']}"
    status, etag = save(ada, note["id"], "Text", ada.get(url).headers["ETag"])
    assert status == 200
    status, again = save(ada, note["id"], "Text", etag)
    assert (status, again) == (200, etag)
    assert ada.get(f"{url}/history").json() == []
    with pytest.raises(LookupError):
        notes.save(db, uuid.uuid4(), "Text", "0", None)
