"""The MCP server: tools over Streamable HTTP, acting through a token."""

import base64
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.conftest import FakeDOIRegistry
from tests.pdfs import make_pdf
from tests.people import Person, group

ACCEPT = "application/json, text/event-stream"


class Assistant:
    """An MCP client with one access token."""

    def __init__(self, client: TestClient, token: str) -> None:
        self.client = client
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": ACCEPT,
            "MCP-Protocol-Version": "2025-06-18",
        }

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.client.post(
            "/mcp",
            headers=self.headers,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body["result"]

    def call(self, tool: str, **arguments: object) -> Any:  # noqa: ANN401 (any JSON)
        result = self.rpc("tools/call", {"name": tool, "arguments": arguments})
        if result["isError"]:
            raise ToolFailed(result["content"][0]["text"])
        content = result["structuredContent"]
        # Lists come wrapped (MCP's structured output is an object).
        return content["result"] if set(content) == {"result"} else content


class ToolFailed(Exception):
    pass


def token(person: Person, *scopes: str, **extra: object) -> str:
    response = person.post(
        "/api/me/tokens", json={"name": "assistant", "scopes": list(scopes), **extra}
    )
    assert response.status_code == 201, response.text
    raw: str = response.json()["token"]
    return raw


ALL = (
    "search",
    "papers.read",
    "files.read",
    "tags.write",
    "papers.write",
    "notes.write",
)


@pytest.fixture
def ada(client: TestClient, db: Session, blobs: BlobStore) -> Person:
    """Ada with a paper whose PDF has searchable text."""
    person = Person(client, db, "ada")
    paper = person.post(
        "/api/items",
        json={
            "metadata": {
                "title": "Radar gap filling",
                "abstract": "Filling gaps below the beam.",
            }
        },
    ).json()
    pdf = make_pdf(
        [
            ["Radar gap filling", "Blind zones below the beam hide rainfall."],
            ["Methods", "We fill the gaps with a diffusion model."],
        ]
    )
    file = person.post(
        f"/api/items/{paper['id']}/files",
        files={"upload": ("radar.pdf", pdf, "application/pdf")},
    ).json()
    process_file(db, blobs, uuid.UUID(file["id"]))
    return person


def test_handshake_and_tools(client: TestClient, ada: Person) -> None:
    assistant = Assistant(client, token(ada, *ALL))
    init = assistant.rpc(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    )
    assert "Cite every claim" in init["instructions"]
    tools = {t["name"]: t for t in assistant.rpc("tools/list")["tools"]}
    assert set(tools) == {
        "search",
        "get_passage",
        "get_abstracts",
        "get_document",
        "get_file",
        "export_citations",
        "my_access",
        "list_collections",
        "list_documents",
        "list_tags",
        "add_tags",
        "add_document",
        "get_note",
        "create_note",
        "update_note",
    }
    assert tools["search"]["annotations"]["readOnlyHint"] is True
    assert tools["add_tags"]["annotations"]["readOnlyHint"] is False
    # Without a token, nothing.
    response = client.post(
        "/mcp",
        headers={"Accept": ACCEPT},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 401


def test_search_and_read(client: TestClient, ada: Person) -> None:
    assistant = Assistant(client, token(ada, *ALL))
    found = assistant.call("search", query="diffusion", mode="keyword")
    [paper] = found["papers"]
    assert paper["title"] == "Radar gap filling"
    assert paper["link"].startswith("https://testserver/items/")
    assert "abstract" not in paper
    [hit] = paper["passages"]
    assert hit["page"] == 2
    assert "diffusion" in hit["text"] and "<mark>" not in hit["text"]
    # Compact: no repeated titles or ids per passage, no empty fields.
    assert set(hit) == {"n", "page", "text"}
    result = assistant.rpc(
        "tools/call", {"name": "search", "arguments": {"query": "diffusion"}}
    )
    assert "\n " not in result["content"][0]["text"]

    passage = assistant.call(
        "get_passage", file_id=paper["file_id"], n=hit["n"], context=1
    )
    assert len(passage["passages"]) >= 2 and "page=2" in passage["link"]
    with_abstract = assistant.call("search", query="diffusion", abstracts=True)
    assert with_abstract["papers"][0]["abstract"] == "Filling gaps below the beam."
    [abstract] = assistant.call("get_abstracts", paper_ids=[paper["paper_id"]])
    assert abstract["abstract"] == "Filling gaps below the beam."
    hit = {"paper_id": paper["paper_id"]}
    details = assistant.call("get_document", paper_id=hit["paper_id"])
    assert details["versions"][0]["files"] == ["radar.pdf"]
    text = assistant.call("get_document", paper_id=hit["paper_id"], part="text")
    assert "Blind zones" in text["text"] and text["truncated"] is False
    page_two = assistant.call(
        "get_document", paper_id=hit["paper_id"], part="text", first_page=2
    )
    assert "Blind zones" not in page_two["text"]
    [file] = details["files"]
    assert file["filename"] == "radar.pdf" and file["media_type"] == "application/pdf"
    assert file["download"].endswith(f"/api/files/{file['file_id']}/content")
    # The download link works with the token.
    download = client.get(
        file["download"].removeprefix("https://testserver"),
        headers={"Authorization": assistant.headers["Authorization"]},
    )
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")

    result = assistant.rpc(
        "tools/call", {"name": "get_file", "arguments": {"file_id": file["file_id"]}}
    )
    assert not result["isError"]
    note, embedded = result["content"]
    assert "radar.pdf" in note["text"]
    assert embedded["resource"]["mimeType"] == "application/pdf"
    assert base64.b64decode(embedded["resource"]["blob"]) == download.content
    with pytest.raises(ToolFailed, match="No such file"):
        assistant.call("get_file", file_id=str(uuid.uuid4()))

    result = assistant.rpc(
        "tools/call",
        {"name": "export_citations", "arguments": {"paper_ids": [paper["paper_id"]]}},
    )
    assert result["content"][0]["text"].startswith("@misc{noauthor_radar_nodate,")
    with pytest.raises(ToolFailed, match="Give paper_ids"):
        assistant.call("export_citations")

    papers = assistant.call("list_documents", title="radar")
    assert papers["total"] == 1
    with pytest.raises(ToolFailed, match="No such paper"):
        assistant.call("get_document", paper_id=str(uuid.uuid4()))


def test_scopes_and_owner_limits(client: TestClient, db: Session, ada: Person) -> None:
    only_search = Assistant(client, token(ada, "search"))
    assert only_search.call("search", query="radar", mode="keyword")["papers"]
    with pytest.raises(ToolFailed, match=r"lacks the scope papers\.read"):
        only_search.call("list_documents")
    no_files = Assistant(client, token(ada, "papers.read"))
    paper = no_files.call("list_documents")["papers"][0]
    with pytest.raises(ToolFailed, match=r"files\.read"):
        no_files.call("get_document", paper_id=paper["paper_id"], part="text")
    with pytest.raises(ToolFailed, match=r"tags\.write"):
        no_files.call("add_tags", paper_ids=[paper["paper_id"]], tags=["x"])
    file_id = no_files.call("get_document", paper_id=paper["paper_id"])["files"][0]
    with pytest.raises(ToolFailed, match=r"files\.read"):
        no_files.call("get_file", file_id=file_id["file_id"])

    # A token limited to a group sees nothing of Ada's own papers.
    root = Person(client, db, "root", admin=True)
    chair = group(root, "Chair", ada)
    ada.add("Group paper", chair["library_id"])
    only_chair = Assistant(client, token(ada, *ALL, library_ids=[chair["library_id"]]))
    titles = [p["title"] for p in only_chair.call("list_documents")["papers"]]
    assert titles == ["Group paper"]
    assert only_chair.call("search", query="radar", mode="keyword")["papers"] == []

    # The assistant can see what it may do.
    rights = only_chair.call("my_access")
    assert rights["acting_for"] == "ada" and rights["sees"] == "only: Chair"
    assert "groups" not in rights and "expires" not in rights
    assert {"search", "get_file", "add_tags", "my_access"} <= set(rights["tools"])
    with_groups = Assistant(client, token(ada, "groups.read", expires_in_days=30))
    rights = with_groups.call("my_access")
    assert rights["tools"] == ["my_access"] and rights["sees"].startswith("everything")
    assert rights["groups"] == [
        {"group": "Chair", "role": "admin", "may_add_and_change": True}
    ]
    assert rights["expires"]

    # Revoked: refused at once.
    listed = ada.get("/api/me/tokens").json()
    ada.delete(f"/api/me/tokens/{listed[0]['id']}")
    with pytest.raises(ToolFailed, match="invalid, expired or revoked"):
        Assistant(client, "paperus_" + "x" * 43).call("list_tags")


def test_writing(
    client: TestClient, db: Session, ada: Person, doi_registry: FakeDOIRegistry
) -> None:
    doi_registry.records["10.1234/radar"] = {
        "type": "journal-article",
        "title": "Radar climatology",
    }
    assistant = Assistant(client, token(ada, *ALL))
    added = assistant.call("add_document", doi="10.1234/radar")
    assert (added["title"], added["added"]) == ("Radar climatology", True)
    again = assistant.call("add_document", doi="https://doi.org/10.1234/RADAR")
    assert (again["paper_id"], again["added"]) == (added["paper_id"], False)
    tagged = assistant.call("add_tags", paper_ids=[added["paper_id"]], tags=["climate"])
    assert tagged == [{"paper_id": added["paper_id"], "tags": ["climate"]}]
    assert [t["name"] for t in assistant.call("list_tags")] == ["climate"]

    # A reader's assistant tags group papers only privately.
    root = Person(client, db, "root", admin=True)
    bob = Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    shared = ada.add("Shared", chair["library_id"])
    bobs = Assistant(client, token(bob, *ALL))
    bobs.call("add_tags", paper_ids=[shared["id"]], tags=["to read"])
    assert ada.get(f"/api/items/{shared['id']}").json()["tags"] == []
    with pytest.raises(ToolFailed, match=r"lacks the scope|may not"):
        Assistant(client, token(bob, "papers.read")).call(
            "add_document", doi="10.1234/radar"
        )


def test_notes(client: TestClient, ada: Person) -> None:
    assistant = Assistant(client, token(ada, *ALL))
    [paper] = assistant.call("list_documents", title="radar")["papers"]
    created = assistant.call(
        "create_note",
        text="# Summary by Claude\n\nThe gaps below the beam are filled by diffusion.",
        paper_ids=[paper["paper_id"]],
    )
    assert created["title"] == "Summary by Claude"
    assert created["link"].endswith(f"/notes/{created['note_id']}")
    note = assistant.call("get_note", note_id=created["note_id"])
    assert note["about"] == [
        {"paper_id": paper["paper_id"], "title": "Radar gap filling"}
    ]
    assert "shared_with" not in note  # private
    details = assistant.call("get_document", paper_id=paper["paper_id"])
    assert details["notes"] == [
        {"note_id": created["note_id"], "title": "Summary by Claude"}
    ]
    # Found by search, apart from papers.
    found = assistant.call("search", query="beam", mode="keyword")
    [hit] = found["notes"]
    assert hit["note"] == "Summary by Claude" and "beam" in hit["passages"][0]["text"]
    # Updating needs the current change number.
    with pytest.raises(ToolFailed, match="changed in the meantime"):
        assistant.call(
            "update_note", note_id=hit["note_id"], text="x", change=note["change"] - 1
        )
    updated = assistant.call(
        "update_note", note_id=hit["note_id"], text="# Better", change=note["change"]
    )
    assert updated["change"] > note["change"]
    assert ada.get(f"/api/notes/{hit['note_id']}").json()["title"] == "Better"
    # Without notes.write: reading only.
    reader = Assistant(client, token(ada, "papers.read"))
    assert reader.call("get_note", note_id=hit["note_id"])["title"] == "Better"
    with pytest.raises(ToolFailed, match=r"notes\.write"):
        reader.call("create_note", text="x")
    with pytest.raises(ToolFailed, match="no group called"):
        assistant.call("create_note", text="x", group="Nowhere")


def test_full_text_needs_files_read_and_no_trash(
    client: TestClient, ada: Person
) -> None:
    searcher = Assistant(client, token(ada, "search"))
    [paper] = searcher.call("search", query="diffusion", mode="keyword")["papers"]
    hit = paper["passages"][0]
    # Search gives snippets; the full passage needs the right to read files.
    with pytest.raises(ToolFailed, match=r"files\.read"):
        searcher.call("get_passage", file_id=paper["file_id"], n=hit["n"])
    reader = Assistant(client, token(ada, *ALL))
    assert reader.call("get_passage", file_id=paper["file_id"], n=hit["n"])
    # A paper in the trash is out of reach.
    ada.delete(f"/api/items/{paper['paper_id']}")
    with pytest.raises(ToolFailed, match="No such passage"):
        reader.call("get_passage", file_id=paper["file_id"], n=hit["n"])
    with pytest.raises(ToolFailed, match="No such file"):
        reader.call("get_file", file_id=paper["file_id"])
    with pytest.raises(ToolFailed, match="1 to 500"):
        reader.call("search", query="x" * 501)
