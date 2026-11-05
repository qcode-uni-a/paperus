"""Notes: titles, the edit history, conflicts, trash and export."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from paperus.models import Note, NoteChunk
from tests.people import Person


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
