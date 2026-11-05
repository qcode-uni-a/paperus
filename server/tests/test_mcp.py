"""The MCP server: tools over Streamable HTTP, acting through a token."""

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


ALL = ("search", "papers.read", "files.read", "tags.write", "papers.write")


@pytest.fixture
def ada(client: TestClient, db: Session, blobs: BlobStore) -> Person:
    """Ada with a paper whose PDF has searchable text."""
    person = Person(client, db, "ada")
    paper = person.add("Radar gap filling")
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
        "get_document",
        "list_collections",
        "list_documents",
        "list_tags",
        "add_tags",
        "add_document",
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
    [hit] = found["passages"]
    assert hit["paper_title"] == "Radar gap filling"
    assert hit["page"] == 2
    assert "diffusion" in hit["text"] and "<mark>" not in hit["text"]
    assert (
        hit["link"].startswith("https://testserver/items/") and "page=2" in hit["link"]
    )

    passage = assistant.call("get_passage", passage_id=hit["passage_id"], context=1)
    assert len(passage["passages"]) >= 2
    details = assistant.call("get_document", paper_id=hit["paper_id"])
    assert details["versions"][0]["files"] == ["radar.pdf"]
    text = assistant.call("get_document", paper_id=hit["paper_id"], part="text")
    assert "Blind zones" in text["text"] and text["truncated"] is False
    page_two = assistant.call(
        "get_document", paper_id=hit["paper_id"], part="text", first_page=2
    )
    assert "Blind zones" not in page_two["text"]
    papers = assistant.call("list_documents", title="radar")
    assert papers["total"] == 1
    with pytest.raises(ToolFailed, match="No such paper"):
        assistant.call("get_document", paper_id=str(uuid.uuid4()))


def test_scopes_and_owner_limits(client: TestClient, db: Session, ada: Person) -> None:
    only_search = Assistant(client, token(ada, "search"))
    assert only_search.call("search", query="radar", mode="keyword")["passages"]
    with pytest.raises(ToolFailed, match=r"lacks the scope papers\.read"):
        only_search.call("list_documents")
    no_files = Assistant(client, token(ada, "papers.read"))
    paper = no_files.call("list_documents")["papers"][0]
    with pytest.raises(ToolFailed, match=r"files\.read"):
        no_files.call("get_document", paper_id=paper["paper_id"], part="text")
    with pytest.raises(ToolFailed, match=r"tags\.write"):
        no_files.call("add_tags", paper_ids=[paper["paper_id"]], tags=["x"])

    # A token limited to a group sees nothing of Ada's own papers.
    root = Person(client, db, "root", admin=True)
    chair = group(root, "Chair", ada)
    ada.add("Group paper", chair["library_id"])
    only_chair = Assistant(client, token(ada, *ALL, library_ids=[chair["library_id"]]))
    titles = [p["title"] for p in only_chair.call("list_documents")["papers"]]
    assert titles == ["Group paper"]
    assert only_chair.call("search", query="radar", mode="keyword")["passages"] == []

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
