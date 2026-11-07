"""The MCP server's reading and writing tools at their limits, and what
they refuse: wrong ids, other people's papers, readers and narrow tokens."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus import mcp_server
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.pdfs import make_pdf
from tests.people import Person, group
from tests.test_mcp import ALL, Assistant, ToolFailed, token

TIDY = (*ALL, "collections.write")


def with_pdf(
    person: Person,
    db: Session,
    blobs: BlobStore,
    metadata: dict[str, Any],
    pages: list[list[str]],
    library: str | None = None,
) -> tuple[str, str]:
    """A paper with a searchable PDF: its id and the file's."""
    paper = person.post(
        "/api/items", json={"metadata": metadata, "library_id": library}
    ).json()
    file = person.post(
        f"/api/items/{paper['id']}/files",
        files={"upload": ("paper.pdf", make_pdf(pages), "application/pdf")},
    ).json()
    process_file(db, blobs, uuid.UUID(file["id"]))
    return paper["id"], file["id"]


def long_page(number: int) -> list[str]:
    return [
        f"Radar beams sweep the sky above station {number}, line {line}."
        for line in range(40)
    ]


def test_search_and_reading_at_their_limits(
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ada = Person(client, db, "ada")
    paper, file_id = with_pdf(
        ada,
        db,
        blobs,
        {
            "title": "Radar gap filling",
            "author": [{"family": "Lovelace", "given": "Ada"}],
            "issued": {"date-parts": [[2024]]},
        },
        [long_page(1), long_page(2), long_page(3)],
    )
    with_pdf(ada, db, blobs, {"title": "Radar climatology"}, [["Radar in the Alps"]])
    ai = Assistant(client, token(ada, *ALL))

    # How people name a paper: authors and year, when known.
    both = ai.call("search", query="radar", mode="keyword", limit=2)["papers"]
    found = next(p for p in both if p["paper_id"] == paper)
    assert (found["authors"], found["year"]) == ("Lovelace", 2024)
    climatology = next(p for p in both if p["paper_id"] != paper)
    assert "authors" not in climatology and "year" not in climatology
    assert len(ai.call("search", query="radar", mode="keyword", limit=1)["papers"]) == 1
    with pytest.raises(ToolFailed, match="1 to 500"):
        ai.call("search", query="  ")

    # The text, in parts: where to go on is in the answer.
    first = ai.call("get_document", paper_id=paper, part="text", max_characters=1)
    assert first["truncated"] is True
    assert first["hint"] == f"Continue with start={first['next']}."
    rest = ai.call("get_document", paper_id=paper, part="text", start=first["next"])
    assert rest["text"] and rest["text"] not in first["text"]
    page_one = ai.call("get_document", paper_id=paper, part="text", last_page=1)
    assert page_one["pages"] == [1, 1] and "station 2" not in page_one["text"]
    no_file = ada.add("Without a file")
    with pytest.raises(ToolFailed, match="no file with text"):
        ai.call("get_document", paper_id=no_file["id"], part="text")

    with pytest.raises(ToolFailed, match="No such passage"):
        ai.call("get_passage", file_id=file_id, n=10_000)
    with pytest.raises(ToolFailed, match="Not an id: 'radar'"):
        ai.call("get_passage", file_id="radar", n=0)
    monkeypatch.setattr(mcp_server, "MAX_FILE_BYTES", 100)
    with pytest.raises(ToolFailed, match="larger than"):
        ai.call("get_file", file_id=file_id)

    # Citations of nothing there.
    with pytest.raises(ToolFailed, match="No such papers"):
        ai.call("export_citations", paper_ids=[str(uuid.uuid4())])
    with pytest.raises(ToolFailed, match="No such collection"):
        ai.call("export_citations", collection_id=str(uuid.uuid4()))


def test_listing_by_collection_and_tag(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    radar = ada.add("Radar gap filling")
    ada.add("Rain gauges")
    ai = Assistant(client, token(ada, *TIDY))
    made = ai.call("create_collection", name="Radar")
    inner = ai.call("create_collection", name="Inner", inside="radar")
    ai.call("add_to_collection", paper_ids=[radar["id"]], collection_name="Inner")
    ai.call("add_tags", paper_ids=[radar["id"]], tags=["weather"])

    # A collection lists what is inside its subcollections too.
    listed = ai.call("list_documents", collection_id=made["collection_id"])
    assert [p["title"] for p in listed["papers"]] == ["Radar gap filling"]
    collections = {c["name"]: c for c in ai.call("list_collections")}
    assert collections["Inner"]["inside"] == "Radar"
    assert collections["Inner"]["collection_id"] == inner["collection_id"]
    assert collections["Radar"]["papers"] == 1
    tagged = ai.call("list_documents", tag=" Weather ")["papers"]
    assert [p["title"] for p in tagged] == ["Radar gap filling"]
    with pytest.raises(ToolFailed, match="No such collection"):
        ai.call("list_documents", collection_id=str(uuid.uuid4()))
    with pytest.raises(ToolFailed, match="1 to 100 characters"):
        ai.call("add_tags", paper_ids=[radar["id"]], tags=[" "])


def test_notes_at_their_limits(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ada = Person(client, db, "ada")
    ai = Assistant(client, token(ada, *ALL))
    with pytest.raises(ToolFailed, match="No such note"):
        ai.call("get_note", note_id=str(uuid.uuid4()))
    note = ai.call("create_note", text="# Draft")
    monkeypatch.setattr(mcp_server, "MAX_NOTE", 10)
    with pytest.raises(ToolFailed, match="too long"):
        ai.call("create_note", text="# A long note")
    with pytest.raises(ToolFailed, match="too long"):
        ai.call(
            "update_note", note_id=note["note_id"], text="# A long note", change="1"
        )
    # In the trash: gone for the assistant.
    ada.delete(f"/api/notes/{note['note_id']}")
    with pytest.raises(ToolFailed, match="No such note"):
        ai.call("get_note", note_id=note["note_id"])


def test_other_people_groups_and_readers(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    bob = Person(client, db, "bob")
    eve = Person(client, db, "eve")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    own, own_file = with_pdf(ada, db, blobs, {"title": "Ada's own"}, [["Radar"]])
    shared = ada.add("Shared", chair["library_id"])
    ada_note = ada.note("# Private")
    group_note = ada.note("# Chair minutes", chair["library_id"])

    # Someone else's things are as if they did not exist.
    eves = Assistant(client, token(eve, *ALL))
    for tool, arguments in [
        ("get_document", {"paper_id": own}),
        ("get_abstracts", {"paper_ids": [own]}),
        ("find_similar", {"paper_id": own}),
        ("add_tags", {"paper_ids": [own], "tags": ["mine"]}),
        ("create_note", {"text": "# About it", "paper_ids": [own]}),
    ]:
        with pytest.raises(ToolFailed, match="No such paper"):
            eves.call(tool, **arguments)
    with pytest.raises(ToolFailed, match="No such file"):
        eves.call("get_file", file_id=own_file)
    with pytest.raises(ToolFailed, match="No such passage"):
        eves.call("get_passage", file_id=own_file, n=0)
    with pytest.raises(ToolFailed, match="No such note"):
        eves.call("get_note", note_id=ada_note["id"])

    # A group's reader reads its notes but changes none, nor writes there.
    bobs = Assistant(client, token(bob, *ALL))
    read = bobs.call("get_note", note_id=group_note["id"])
    assert read["shared_with"] == "Chair"
    with pytest.raises(ToolFailed, match="may not change this note"):
        bobs.call(
            "update_note",
            note_id=group_note["id"],
            text="# Mine",
            change=read["change"],
        )
    with pytest.raises(ToolFailed, match="readers cannot change"):
        bobs.call("create_note", text="# Mine", group="Chair")
    # Limited to the group: nothing of their own to tag with, or add to.
    only_chair = Assistant(client, token(bob, *ALL, library_ids=[chair["library_id"]]))
    with pytest.raises(ToolFailed, match="may not tag"):
        only_chair.call("add_tags", paper_ids=[shared["id"]], tags=["later"])
    with pytest.raises(ToolFailed, match="may not add anything"):
        only_chair.call("add_document", doi="10.1234/radar")

    # A member writes for the group (named in any case).
    note = Assistant(client, token(ada, *ALL)).call(
        "create_note", text="# For all", group="chair", paper_ids=[shared["id"]]
    )
    assert (
        ada.get(f"/api/notes/{note['note_id']}").json()["library_id"]
        == (chair["library_id"])
    )


def test_what_a_token_sees(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    chair = group(root, "Chair", ada)
    own = ada.libraries()["Me"]["id"]
    rights = Assistant(
        client, token(ada, "papers.read", library_ids=[own, chair["library_id"]])
    ).call("my_access")
    assert rights["sees"] == "only: the person's own, Chair"
    # A group the person is no longer in.
    bob = Person(client, db, "bob")
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "member"})
    left = Assistant(
        client, token(bob, "papers.read", library_ids=[chair["library_id"]])
    )
    assert ada.delete(f"/api/groups/{chair['id']}/members/{bob.id}").status_code == 200
    assert left.call("my_access")["sees"] == "only: an owner no longer reachable"
