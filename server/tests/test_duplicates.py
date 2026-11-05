"""Likely duplicates across the library, and papers without details."""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from paperus.models import File, Item, MetadataSource, TextStatus, Version
from tests.people import Person, group

PDF = b"%PDF-1.7\n" + b"x" * 3000 + b"\n%%EOF\n"


def paper(
    person: Person,
    title: str,
    library: str | None = None,
    doi: str | None = None,
) -> str:
    identifiers = [{"scheme": "doi", "value": doi}] if doi else []
    response = person.post(
        "/api/items",
        json={
            "metadata": {"title": title},
            "library_id": library,
            "identifiers": identifiers,
        },
    )
    assert response.status_code == 201, response.text
    item_id: str = response.json()["id"]
    return item_id


def pairs(person: Person) -> list[dict[str, Any]]:
    response = person.get("/api/duplicates")
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()
    return found


def test_found_by_identifier_file_and_title(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "member"})
    doi = "10.1234/rain"
    # Ada has it privately; Bob, not seeing that, added it to the group.
    mine = paper(ada, "Rain in the Alps", doi=doi)
    shared = paper(bob, "Rain in the Alps (preprint)", chair["library_id"], doi=doi)
    # The same title written differently.
    first = paper(ada, "The diffusion of rain")
    second = paper(ada, "The Diffusion of Rain.")
    # The same file in two papers.
    with_file = [paper(ada, "Scan 1"), paper(ada, "Scan 2")]
    for item in with_file:
        ada.post(
            f"/api/items/{item}/files",
            files={"upload": ("scan.pdf", PDF, "application/pdf")},
        )

    found = pairs(ada)
    assert [p["reasons"] for p in found] == [["identifier"], ["file"], ["title"]]
    by_reason = {p["reasons"][0]: p for p in found}
    assert {
        by_reason["identifier"]["keep"]["id"],
        by_reason["identifier"]["merge"]["id"],
    } == {
        mine,
        shared,
    }
    assert {by_reason["title"]["keep"]["id"], by_reason["title"]["merge"]["id"]} == {
        first,
        second,
    }
    # Bob sees only the group's paper: no pair for him.
    assert pairs(bob) == []
    # Short titles ("Notes") are not compared.
    paper(ada, "Notes")
    paper(ada, "notes")
    assert len(pairs(ada)) == 3

    # Marked as different: gone, for everyone who sees both.
    response = ada.post("/api/duplicates/different", json={"a": second, "b": first})
    assert response.status_code == 204
    assert [p["reasons"] for p in pairs(ada)] == [["identifier"], ["file"]]


def test_recommendation(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    bare = paper(ada, "Clouds over Augsburg")
    rich = paper(ada, "Clouds over Augsburg!")
    ada.post(f"/api/items/{rich}/tags", json={"name": "clouds"})
    ada.post(
        f"/api/items/{rich}/files", files={"upload": ("c.pdf", PDF, "application/pdf")}
    )
    [pair] = pairs(ada)
    assert (pair["keep"]["id"], pair["merge"]["id"]) == (rich, bare)
    assert pair["why"] == ["has the PDF", "has more tags"]
    assert pair["can_merge"] is True

    # A reader of the group's copy: only the own one can go.
    chair = group(root, "Chair", bob)
    bob.put(f"/api/groups/{chair['id']}/members/{ada.id}", json={"role": "reader"})
    shared = paper(bob, "Weather radar gaps", chair["library_id"])
    own = paper(ada, "Weather radar gaps")
    ada.post(f"/api/items/{own}/tags", json={"name": "x"})
    for p in pairs(ada):
        if p["reasons"] == ["title"] and shared in (p["keep"]["id"], p["merge"]["id"]):
            assert (p["keep"]["id"], p["merge"]["id"]) == (shared, own)
            assert p["why"] == ["you can change only the other one"]
            break
    else:
        raise AssertionError("pair not found")


def test_unsorted(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    guessed = paper(ada, "scan_2024_03.pdf")
    meeting = paper(ada, "Meeting notes")  # a Markdown file: no DOI to find
    paper(ada, "A paper with details")
    for item, name, data, kind in (
        (guessed, "scan.pdf", PDF, "application/pdf"),
        (meeting, "notes.md", b"# Meeting", "text/markdown"),
    ):
        ada.post(f"/api/items/{item}/files", files={"upload": (name, data, kind)})
    db.execute(
        update(Version)
        .where(Version.item_id.in_([guessed, meeting]))
        .values(metadata_source=MetadataSource.FILE)
    )
    # Files are read (otherwise they count as still being looked at).
    db.execute(update(File).values(text_status=TextStatus.DONE))
    db.commit()
    unsorted = ada.get("/api/items", params={"unsorted": True}).json()
    assert [i["title"] for i in unsorted] == ["scan_2024_03.pdf"]


def test_merging_keeps_notes_and_stars(client: TestClient, db: Session) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    keep = paper(ada, "Clouds over Augsburg")
    away = paper(ada, "Clouds over Augsburg!")
    note = ada.note("Reading notes", items=[away])
    both = ada.note("Comparison", items=[away, keep])
    ada.put(f"/api/items/{away}/favourite")
    preview = ada.get(f"/api/items/{away}/merge-preview", params={"into": keep}).json()
    notes = {s["name"]: s["action"] for s in preview["steps"] if s["kind"] == "note"}
    assert notes == {"Comparison": "already", "Reading notes": "move"}
    assert ada.post(f"/api/items/{away}/merge", json={"into": keep}).status_code == 200
    assert {n["id"] for n in ada.get(f"/api/notes?item={keep}").json()} == {
        note["id"],
        both["id"],
    }
    assert ada.get(f"/api/items/{keep}").json()["favourite"] is True
    assert bob.get("/api/notes").json() == []


def test_readers_cannot_dismiss_for_the_group(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    a = paper(ada, "Weather radar gaps", chair["library_id"])
    b = paper(ada, "Weather radar gaps.", chair["library_id"])
    response = bob.post("/api/duplicates/different", json={"a": a, "b": b})
    assert response.status_code == 403
    assert len(pairs(ada)) == 1
    # A group that still has notes is not deleted (like one with papers).
    for item in (a, b):
        ada.delete(f"/api/items/{item}")
    db.execute(update(Item).values(library_id=uuid.UUID(ada.libraries()["Me"]["id"])))
    db.commit()
    ada.note("Group note", chair["library_id"])
    assert root.delete(f"/api/groups/{chair['id']}").status_code == 409


def test_same_title_by_other_authors_is_no_duplicate(
    client: TestClient, db: Session
) -> None:
    """Two books called "Introduction to Quantum Optics" by different
    authors are two works; with the same first author (or none) a pair."""
    ada = Person(client, db, "ada")

    def add(title: str, *families: str) -> str:
        metadata = {"title": title, "author": [{"family": f} for f in families]}
        item: str = ada.post("/api/items", json={"metadata": metadata}).json()["id"]
        return item

    add("Introduction to Quantum Optics", "Navarrete-Benlloch")
    add("Introduction to Quantum Optics", "Grynberg", "Aspect", "Fabre")
    same = {
        add("Floquet engineering of qubits", "Peri"),
        add("Floquet Engineering of Qubits", "Peri", "Benito"),
    }
    anonymous = {
        add("A lecture on spin qubits"),
        add("A lecture on spin qubits", "Burkard"),
    }
    pairs = ada.get("/api/duplicates").json()
    found = [{p["keep"]["id"], p["merge"]["id"]} for p in pairs]
    assert sorted(found, key=sorted) == sorted([same, anonymous], key=sorted)
