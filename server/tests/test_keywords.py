"""Keywords (from a paper's details: arXiv categories, a publisher's
subjects, the authors' keywords) are kept apart from the person's tags."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus import organize
from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedPaper, bibtex
from paperus.importing.apply import apply
from paperus.models import Item, TagSource
from paperus.storage import BlobStore
from tests.people import Person, group
from tests.test_import import access_of, zipped
from tests.test_mcp import Assistant
from tests.test_tokens import make_token

MENDELEY = """@article{Smith2020,
author = {Smith, Anna},
title = {{Radar gaps over the Alps}},
doi = {10.1234/radar},
keywords = {Doppler radar,To read,mesoscale},
mendeley-tags = {To read},
year = {2020}
}
"""


def test_mendeley_keeps_the_persons_tags_apart() -> None:
    [paper] = bibtex.read(MENDELEY).papers
    assert paper.tags == ["To read"]
    assert paper.keywords == ["Doppler radar", "mesoscale"]
    # Elsewhere (JabRef, Zotero's BibTeX) keywords are the person's.
    [plain] = bibtex.read(MENDELEY.replace("mendeley-tags = {To read},\n", "")).papers
    assert (plain.tags, plain.keywords) == (
        ["Doppler radar", "To read", "mesoscale"],
        [],
    )


def _tags(person: Person, item_id: str) -> dict[str, str]:
    item = person.get(f"/api/items/{item_id}").json()
    return {tag["name"]: tag["source"] for tag in item["tags"]}


def test_imported_keywords(client: TestClient, db: Session, blobs: BlobStore) -> None:
    ada = Person(client, db, "ada")
    owner = uuid.UUID(ada.libraries()["Me"]["id"])

    def run(tags: list[str], automatic: list[str]) -> str:
        paper = ExportedPaper(
            csl={"type": "article-journal", "title": "Radar gaps"},
            identifiers=[(Scheme.DOI, "10.1234/radar")],
            tags=tags,
            keywords=automatic,
            source_key="radar",
        )
        export = Export(format="zotero-rdf", papers=[paper])
        apply(
            db, blobs, access_of(db, ada), export, zipped(),
            owner=owner, max_file_bytes=1000,
        )  # fmt: skip
        [item] = ada.get("/api/items").json()
        return str(item["id"])

    # As an earlier import took them: all as the person's own.
    item_id = run(["Quantum Physics", "To read"], [])
    assert _tags(ada, item_id) == {"Quantum Physics": "manual", "To read": "manual"}
    # The same export again, now read properly, sorts them.
    run(["To read"], ["Quantum Physics", "To read", "Qubits"])
    assert _tags(ada, item_id) == {
        "Quantum Physics": "automatic",
        "Qubits": "automatic",
        "To read": "manual",
    }
    tags = {t["name"]: t for t in ada.get("/api/tags").json()}
    assert tags["Qubits"]["sources"] == {"automatic": 1}

    # Put on by hand, a keyword becomes one of the person's tags.
    response = ada.post(f"/api/items/{item_id}/tags", json={"name": "qubits"})
    assert response.status_code == 201, response.text
    assert _tags(ada, item_id)["Qubits"] == "manual"


def test_removing_keywords(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    bob = Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    group(root, "Readers", bob)
    lab_library = ada.libraries()["Lab"]["id"]
    mine = ada.add("Mine")
    shared = ada.add("Shared", library=lab_library)

    def tag_automatically(item_id: str, *names: str) -> None:
        item = db.get(Item, uuid.UUID(item_id))
        assert item is not None
        for name in names:
            organize.tag_item(
                db,
                item,
                name,
                library_id=item.library_id,
                source=TagSource.AUTOMATIC,
            )
        db.commit()

    tag_automatically(mine["id"], "Quantum Physics", "Optics")
    tag_automatically(shared["id"], "Quantum Physics")
    assert (
        ada.post(f"/api/items/{mine['id']}/tags", json={"name": "Optics"}).status_code
        == 201
    )
    assert (
        ada.post(f"/api/items/{mine['id']}/tags", json={"name": "To read"}).status_code
        == 201
    )

    # AI assistants see which tags no person put on.
    token = make_token(ada, scopes=["papers.read"])["token"]
    listed = {
        t["name"]: t["keyword"] for t in Assistant(client, token).call("list_tags")
    }
    assert listed == {"Optics": False, "Quantum Physics": True, "To read": False}

    # Someone who may change neither library removes nothing.
    assert bob.post("/api/tags/remove-keywords").json() == {"links": 0, "tags": 0}
    removed = ada.post("/api/tags/remove-keywords").json()
    # Both papers lose "Quantum Physics" (the tag goes); "Optics" was put on
    # by hand, so it stays, like "To read".
    assert removed == {"links": 2, "tags": 2}
    assert _tags(ada, mine["id"]) == {"Optics": "manual", "To read": "manual"}
    assert _tags(ada, shared["id"]) == {}
    names = sorted(t["name"] for t in ada.get("/api/tags").json())
    assert names == ["Optics", "To read"]
    assert lab  # the group stays
