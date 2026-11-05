"""Likely duplicates across the library, and papers without details."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from paperus.models import MetadataSource, Version
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
    paper(ada, "A paper with details")
    db.execute(
        update(Version)
        .where(Version.item_id == guessed)
        .values(metadata_source=MetadataSource.FILE)
    )
    db.commit()
    unsorted = ada.get("/api/items", params={"unsorted": True}).json()
    assert [i["title"] for i in unsorted] == ["scan_2024_03.pdf"]
