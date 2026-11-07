"""Tidying through MCP at its edges: what it refuses (other people's papers,
readers, wrong ids and names) and open-access copies fetched for a paper."""

import uuid
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from sqlalchemy import update
from sqlalchemy.orm import Session

from paperus.app import create_app
from paperus.config import Settings
from paperus.models import File, TextStatus
from tests.conftest import FakeDOIRegistry, FakeML
from tests.pdfs import make_pdf
from tests.people import Person, group
from tests.test_mcp import ALL, Assistant, ToolFailed, token

TIDY = (*ALL, "collections.write")
GOOD = make_pdf([["Floquet engineering of spin qubits"]])
BROKEN = b"%PDF-1.7\n1 0 obj << /Type /Catalog"  # cut off


def with_file(person: Person, db: Session, item_id: str) -> str:
    """A file whose text could not be read, on the paper."""
    file: dict[str, Any] = person.post(
        f"/api/items/{item_id}/files",
        files={"upload": ("damaged.pdf", BROKEN, "application/pdf")},
    ).json()
    db.execute(
        update(File)
        .where(File.id == uuid.UUID(file["id"]))
        .values(text_status=TextStatus.FAILED, text_error="damaged")
    )
    db.commit()
    return file["id"]


def test_others_and_readers_change_nothing(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    bob = Person(client, db, "bob")
    eve = Person(client, db, "eve")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    own = ada.add("Ada's paper")["id"]
    shared = ada.add("Shared")["id"]
    ada.put(f"/api/items/{shared}/owner", json={"library_id": chair["library_id"]})
    trashed = ada.add("Shared too", chair["library_id"])["id"]
    ada.delete(f"/api/items/{trashed}")
    file_id = with_file(ada, db, shared)
    ai = Assistant(client, token(ada, *TIDY))
    ai.call("add_tags", paper_ids=[shared], tags=["methods"])
    reading = ai.call("create_collection", name="Chair reading", group="Chair")
    ai.call("add_to_collection", paper_ids=[shared], collection_name="Chair reading")

    # Someone else's: as if it did not exist.
    eves = Assistant(client, token(eve, *TIDY))
    for tool, arguments in [
        ("merge_papers", {"keep_id": own, "other_id": own}),
        ("not_duplicates", {"paper_a": own, "paper_b": shared}),
        ("set_doi", {"paper_id": own, "doi": "10.1234/x"}),
        ("download_open_access", {"paper_id": own}),
        ("mark_file_not_needed", {"paper_ids": [own]}),
        ("archive_papers", {"paper_ids": [own]}),
        ("remove_tags", {"paper_ids": [own], "tags": ["methods"]}),
        ("restore_papers", {"paper_ids": [trashed]}),
    ]:
        with pytest.raises(ToolFailed, match="No such paper"):
            eves.call(tool, **arguments)
    with pytest.raises(ToolFailed, match="No such file"):
        eves.call("retry_file", file_id=file_id)
    for name in ("Chair reading", reading["collection_id"]):
        with pytest.raises(ToolFailed, match="No collection"):
            eves.call("add_to_collection", paper_ids=[own], collection_name=name)
    with pytest.raises(ToolFailed, match="no group called 'Chair'"):
        eves.call("create_collection", name="Mine", group="Chair")
    with pytest.raises(ToolFailed, match="no tag “methods”"):
        eves.call("rename_tag", name="methods", new_name="Methods")

    # A reader sees the group's papers, but tidies none of them.
    bobs = Assistant(client, token(bob, *TIDY))
    with pytest.raises(ToolFailed, match="may not change “Shared”"):
        bobs.call("mark_file_not_needed", paper_ids=[shared])
    with pytest.raises(ToolFailed, match="may not change “Shared too”"):
        bobs.call("restore_papers", paper_ids=[trashed])
    with pytest.raises(ToolFailed, match="change neither"):
        bobs.call("not_duplicates", paper_a=shared, paper_b=shared)
    with pytest.raises(ToolFailed, match="may not change the tag"):
        bobs.call("remove_tags", paper_ids=[shared], tags=["methods"])
    with pytest.raises(ToolFailed, match="no tag “methods” you may change"):
        bobs.call("rename_tag", name="methods", new_name="Methods", group="Chair")
    for tool in ("add_to_collection", "remove_from_collection"):
        with pytest.raises(ToolFailed, match="may not change this collection"):
            bobs.call(tool, paper_ids=[shared], collection_name="Chair reading")
    with pytest.raises(ToolFailed, match="may not add collections there"):
        bobs.call("create_collection", name="Mine", group="Chair")
    with pytest.raises(ToolFailed, match="may not add collections there"):
        bobs.call("create_collection", name="Mine", inside="Chair reading")
    with pytest.raises(ToolFailed, match="may not change this paper's files"):
        bobs.call("retry_file", file_id=file_id)
    with pytest.raises(ToolFailed, match="No such file"):
        bobs.call("retry_file", file_id=str(uuid.uuid4()))
    # Restored by a member, from the trash only.
    [restored] = ai.call("restore_papers", paper_ids=[trashed])
    assert restored["title"] == "Shared too"
    assert ai.call("list_trash") == []


def test_wrong_ids_names_and_dois(
    client: TestClient, db: Session, doi_registry: FakeDOIRegistry
) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    chair = group(root, "Chair", ada)
    own = ada.add("Floquet qubits")["id"]
    ai = Assistant(client, token(ada, *TIDY))

    with pytest.raises(ToolFailed, match="Not an id: 'nope'"):
        ai.call("set_doi", paper_id="nope", doi="10.1234/x")
    with pytest.raises(ToolFailed, match="into itself"):
        ai.call("merge_papers", keep_id=own, other_id=own)
    with pytest.raises(ToolFailed, match="section is"):
        ai.call("list_missing_pdfs", section="books")
    assert ai.call("list_missing_pdfs", section="journal") == []

    # DOIs: none, unknown, a registry that does not answer properly.
    with pytest.raises(ToolFailed, match="not a valid doi"):
        ai.call("set_doi", paper_id=own, doi="not a doi")
    with pytest.raises(ToolFailed, match=r"No paper has the DOI 10\.1234/unknown"):
        ai.call("set_doi", paper_id=own, doi="10.1234/unknown")
    doi_registry.records["10.1234/odd"] = ["not", "an", "object"]
    with pytest.raises(ToolFailed, match="did not answer"):
        ai.call("set_doi", paper_id=own, doi="10.1234/odd")
    # An arXiv ID is its DOI; set twice, nothing changes.
    doi_registry.records["10.48550/arxiv.2401.12345"] = {
        "type": "article",
        "title": "Floquet qubits",
    }
    first = ai.call("set_doi", paper_id=own, doi="arXiv:2401.12345v2")
    assert "unchanged" not in first
    again = ai.call("set_doi", paper_id=own, doi="2401.12345")
    assert again["unchanged"] is True

    # Nothing open to fetch here (no source answers).
    with pytest.raises(ToolFailed, match="No open copy found"):
        ai.call("download_open_access", paper_id=own)
    with pytest.raises(ToolFailed, match="no published version"):
        ai.call("download_open_access", paper_id=own, journal=True)
    with pytest.raises(ToolFailed, match="No good copy found"):
        ai.call("retry_file", file_id=with_file(ada, db, own), download=True)

    # Tags of the same name: the person's own and the group's.
    shared = ada.add("Shared", chair["library_id"])["id"]
    ai.call("add_tags", paper_ids=[shared], tags=["methods", "radar"])
    ai.call("add_tags", paper_ids=[own], tags=["methods"])
    with pytest.raises(ToolFailed, match="Several tags"):
        ai.call("rename_tag", name="methods", new_name="Methods")
    assert ai.call("rename_tag", name="methods", new_name="Methods", group="Chair") == {
        "renamed": "Methods"
    }
    [left] = ai.call("remove_tags", paper_ids=[shared], tags=["Methods"])
    assert left["tags"] == ["radar"]

    # Collections: names, smart ones, the same name twice.
    with pytest.raises(ToolFailed, match="must not be empty"):
        ai.call("create_collection", name="  ")
    with pytest.raises(ToolFailed, match="No collection “Nowhere”"):
        ai.call("create_collection", name="Inner", inside="Nowhere")
    with pytest.raises(ToolFailed, match="No collection"):
        ai.call("add_to_collection", paper_ids=[own], collection_name=str(uuid.uuid4()))
    smart = ada.post("/api/collections", json={"name": "Recent", "rules": {}})
    assert smart.status_code == 201, smart.text
    with pytest.raises(ToolFailed, match="holds no other collections"):
        ai.call("create_collection", name="Inner", inside="Recent")
    with pytest.raises(ToolFailed, match="by its rules"):
        ai.call("add_to_collection", paper_ids=[own], collection_name="Recent")
    ai.call("create_collection", name="Reading")
    ai.call("create_collection", name="Reading", group="Chair")
    with pytest.raises(ToolFailed, match="Several collections"):
        ai.call("add_to_collection", paper_ids=[own], collection_name="reading")


class FakeSources:
    """arXiv: a whole PDF for every paper."""

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "arxiv.org":
            return httpx2.Response(200, content=GOOD)
        return httpx2.Response(404)


@pytest.fixture
def site(
    settings: Settings,
    db: Session,
    doi_registry: FakeDOIRegistry,
    job_app: App,
    fake_ml: FakeML,
) -> Iterator[TestClient]:
    sources = FakeSources()

    def route(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "doi.org":
            return doi_registry(request)
        return sources(request)

    app = create_app(
        settings,
        http_client=httpx2.Client(transport=httpx2.MockTransport(route)),
        job_app=job_app,
        ml_client=fake_ml.client(),
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def test_open_access_copies(site: TestClient, db: Session) -> None:
    ada = Person(site, db, "ada")
    ai = Assistant(site, token(ada, *TIDY))
    preprint = ada.post(
        "/api/items",
        json={
            "metadata": {"title": "Floquet engineering"},
            "identifiers": [{"scheme": "arxiv", "value": "2601.01234"}],
        },
    ).json()["id"]
    [listed] = ai.call("list_missing_pdfs")
    assert listed["open_copy_possible"] is True
    assert ai.call("download_open_access", paper_id=preprint) == {
        "paper_id": preprint,
        "file": "arXiv 2601.01234.pdf",
    }
    assert ai.call("list_missing_pdfs") == []

    # A damaged file replaced by a fresh copy.
    damaged = with_file(ada, db, preprint)
    [unreadable] = ai.call("list_unreadable_files")
    assert unreadable["fresh_copy_possible"] is True
    assert ai.call("retry_file", file_id=damaged, download=True) == {
        "file_id": damaged,
        "replaced": True,
    }
    assert ada.get(f"/api/files/{damaged}/content").content == GOOD
