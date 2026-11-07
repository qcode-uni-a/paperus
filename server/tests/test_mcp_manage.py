"""Tidying the library through MCP: what Manage does in the website."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.conftest import FakeDOIRegistry
from tests.pdfs import make_pdf
from tests.people import Person, group
from tests.test_mcp import ALL, Assistant, ToolFailed, token

TIDY = (*ALL, "collections.write")
DOI = "10.1234/floquet"


def test_duplicates_unsorted_and_trash(
    client: TestClient, db: Session, blobs: BlobStore, doi_registry: FakeDOIRegistry
) -> None:
    doi_registry.records[DOI] = {"type": "journal-article", "title": "Floquet qubits"}
    ada = Person(client, db, "ada")
    ai = Assistant(client, token(ada, *TIDY))
    # A PDF without a DOI in it: only its file name to go on.
    upload = ada.post(
        "/api/uploads",
        files={
            "upload": (
                "scan.pdf",
                make_pdf([["Floquet qubits", "Ada Lovelace"]]),
                "application/pdf",
            )
        },
    ).json()
    process_file(db, blobs, uuid.UUID(upload["file"]["id"]))
    published = ai.call("add_document", doi=DOI)

    checkup = ai.call("library_checkup")
    assert checkup["papers_without_details"]["count"] == 1
    assert checkup["papers_without_pdf"]["count"] == 1
    [unsorted] = ai.call("list_unsorted")
    assert unsorted["file"] == "scan.pdf"
    assert "Floquet qubits" in unsorted["beginning"]

    # Its DOI belongs to the other paper: merge them instead.
    with pytest.raises(ToolFailed, match="merge_papers"):
        ai.call("set_doi", paper_id=unsorted["paper_id"], doi=DOI)
    merged = ai.call(
        "merge_papers", keep_id=published["paper_id"], other_id=unsorted["paper_id"]
    )
    assert merged["kept"]["title"] == "Floquet qubits"
    assert any("scan.pdf" in step for step in merged["done"])
    assert [p["paper_id"] for p in ai.call("list_trash")] == [unsorted["paper_id"]]
    ai.call("restore_papers", paper_ids=[unsorted["paper_id"]])
    assert ai.call("list_trash") == []

    # A paper whose DOI is found by the AI from its text.
    doi_registry.records["10.1234/other"] = {
        "type": "journal-article",
        "title": "Another paper",
    }
    second = ada.post(
        "/api/uploads",
        files={
            "upload": ("other.pdf", make_pdf([["Another paper"]]), "application/pdf")
        },
    ).json()
    process_file(db, blobs, uuid.UUID(second["file"]["id"]))
    fixed = ai.call("set_doi", paper_id=second["item_id"], doi="10.1234/other")
    assert fixed["title"] == "Another paper"

    # Look-alikes kept apart.
    for _ in range(2):
        ada.post(
            "/api/items",
            json={
                "metadata": {
                    "title": "Two papers with the same title",
                    "author": [{"family": "Byron"}],
                }
            },
        )
    [pair] = [
        p
        for p in ai.call("list_duplicates")
        if p["keep"]["title"] == "Two papers with the same title"
    ]
    ai.call(
        "not_duplicates",
        paper_a=pair["keep"]["paper_id"],
        paper_b=pair["other"]["paper_id"],
    )
    assert all(
        p["keep"]["title"] != "Two papers with the same title"
        for p in ai.call("list_duplicates")
    )

    # A reader's token changes nothing.
    reader = Assistant(client, token(ada, "papers.read"))
    with pytest.raises(ToolFailed, match="lacks the scope"):
        reader.call("restore_papers", paper_ids=[unsorted["paper_id"]])


def test_missing_files_tags_and_collections(
    client: TestClient, db: Session, blobs: BlobStore, doi_registry: FakeDOIRegistry
) -> None:
    doi_registry.records[DOI] = {"type": "journal-article", "title": "Floquet qubits"}
    ada = Person(client, db, "ada")
    ai = Assistant(client, token(ada, *TIDY))
    paper = ai.call("add_document", doi=DOI)
    page = ada.add("A web page")

    missing = ai.call("list_missing_pdfs")
    assert {m["title"] for m in missing} == {"Floquet qubits", "A web page"}
    assert next(m for m in missing if m["title"] == "Floquet qubits")["doi"] == DOI
    ai.call("mark_file_not_needed", paper_ids=[page["id"]])
    assert [m["title"] for m in ai.call("list_missing_pdfs")] == ["Floquet qubits"]
    # Archived: off every list until taken out again.
    ai.call("archive_papers", paper_ids=[page["id"]], archived=False)
    ai.call("archive_papers", paper_ids=[paper["paper_id"]])
    assert ai.call("list_missing_pdfs") == []
    listed = ai.call("list_documents", archived=True)["papers"]
    assert [p["title"] for p in listed] == ["Floquet qubits"]
    ai.call("archive_papers", paper_ids=[paper["paper_id"]], archived=False)

    # An unreadable file, read again.
    broken = ada.post(
        f"/api/items/{paper['paper_id']}/files",
        files={"upload": ("broken.pdf", b"%PDF-1.7 cut off", "application/pdf")},
    ).json()
    process_file(db, blobs, uuid.UUID(broken["id"]))
    [unreadable] = ai.call("list_unreadable_files")
    assert unreadable["filename"] == "broken.pdf" and unreadable["error"]
    assert ai.call("retry_file", file_id=broken["id"]) == {
        "file_id": broken["id"],
        "reading": True,
    }

    # Two tags of the same meaning become one.
    ai.call("add_tags", paper_ids=[paper["paper_id"]], tags=["quantum"])
    ai.call("add_tags", paper_ids=[page["id"]], tags=["Quantum Physics"])
    merged = ai.call("rename_tag", name="quantum", new_name="Quantum Physics")
    assert merged == {"merged_into": "Quantum Physics", "papers_added": 1}
    assert [(t["name"], t["papers"]) for t in ai.call("list_tags")] == [
        ("Quantum Physics", 2)
    ]
    assert ai.call("rename_tag", name="Quantum Physics", new_name="Quantum") == {
        "renamed": "Quantum"
    }
    removed = ai.call("remove_tags", paper_ids=[page["id"]], tags=["quantum"])
    assert removed[0]["tags"] == []

    # Collections.
    made = ai.call("create_collection", name="To read")
    ai.call(
        "add_to_collection", paper_ids=[paper["paper_id"]], collection_name="to read"
    )
    listed = {c["name"]: c for c in ai.call("list_collections")}
    assert listed["To read"]["papers"] == 1
    ai.call(
        "remove_from_collection",
        paper_ids=[paper["paper_id"]],
        collection_name=made["collection_id"],
    )
    assert {c["name"]: c for c in ai.call("list_collections")}["To read"]["papers"] == 0
    with pytest.raises(ToolFailed, match="lacks the scope"):
        Assistant(client, token(ada, *ALL)).call("create_collection", name="Nope")


def test_files_listed_trashed_and_restored(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    bob = Person(client, db, "bob")
    lab_group = group(root, "Lab", ada)
    response = ada.put(
        f"/api/groups/{lab_group['id']}/members/{bob.id}", {"role": "reader"}
    )
    assert response.status_code in (200, 204), response.text
    ai = Assistant(client, token(ada, *ALL))

    def attach(item_id: str, name: str, content: bytes, media_type: str) -> str:
        response = client.post(
            f"/api/items/{item_id}/files",
            files={"upload": (name, content, media_type)},
            data={"role": "supplementary"},
            headers=ada.headers,
        )
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    paper = ada.add("Radar", library=ada.libraries()["Lab"]["id"])
    attach(paper["id"], "radar.pdf", b"%PDF-1.7\n1\n%%EOF\n", "application/pdf")
    page = attach(paper["id"], "radar.html", b"<p>Radar</p>", "text/html")
    figure = attach(paper["id"], "fig.png", b"\x89PNG\r\n\x1a\nx", "image/png")
    alone = ada.add("Only a page")
    attach(alone["id"], "page.html", b"<p>Alone</p>", "text/html")

    def names(**filters: object) -> list[str]:
        listed = ai.call("list_files", **filters)
        assert listed["count"] == len(listed["files"])
        return sorted(f["filename"] for f in listed["files"])

    assert names() == ["fig.png", "page.html", "radar.html", "radar.pdf"]
    assert names(media_types=["text/html"]) == ["page.html", "radar.html"]
    assert names(media_types=["image/", "application/pdf"]) == [
        "fig.png",
        "radar.pdf",
    ]
    assert names(next_to_a_pdf=True) == ["fig.png", "radar.html"]
    [listed] = ai.call("list_files", media_types=["image/png"])["files"]
    assert listed["paper"]["title"] == "Radar" and listed["bytes"] == 9
    assert ai.call("list_files", limit=1)["count"] == 4

    # A reader of the group sees the files but may not trash them; others
    # do not see them at all.
    reader = Assistant(client, token(bob, *ALL))
    assert "radar.html" in [f["filename"] for f in reader.call("list_files")["files"]]
    with pytest.raises(ToolFailed, match="only read"):
        reader.call("trash_files", file_ids=[page])
    carol = Assistant(client, token(Person(client, db, "carol"), *ALL))
    with pytest.raises(ToolFailed, match="No such file"):
        carol.call("trash_files", file_ids=[page])
    with pytest.raises(ToolFailed, match="Not an id"):
        ai.call("trash_files", file_ids=["page"])

    assert ai.call("trash_files", file_ids=[page, figure]) == {
        "trashed": [page, figure]
    }
    assert names(next_to_a_pdf=True) == []
    assert names(in_trash=True) == ["fig.png", "radar.html"]
    assert ai.call("restore_files", file_ids=[figure]) == {"restored": [figure]}
    assert names(in_trash=True) == ["radar.html"]
    assert names(next_to_a_pdf=True) == ["fig.png"]
