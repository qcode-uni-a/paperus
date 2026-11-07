"""Saved web pages (Zotero's snapshots): shown without scripts or outside
requests, and tidied away where a PDF of the same version is there."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.api.files import WEB_PAGE_POLICY
from tests.people import Person, group

PDF = b"%PDF-1.7\n" + b"x" * 5000 + b"\n%%EOF\n"
PAGE = b"<html><body><h1>Radar</h1><script>alert(1)</script></body></html>"


def attach(
    person: Person, item_id: str, name: str, content: bytes, media_type: str
) -> dict[str, Any]:
    response = person.client.post(
        f"/api/items/{item_id}/files",
        files={"upload": (name, content, media_type)},
        data={"role": "supplementary"},
        headers=person.headers,
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_opening_files_safely(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Radar")
    page = attach(ada, paper["id"], "radar.html", PAGE, "text/html")
    notes = attach(ada, paper["id"], "notes.txt", b"plain", "text/plain")
    pdf = attach(ada, paper["id"], "radar.pdf", PDF + b"1", "application/pdf")

    def policy(file: dict[str, Any]) -> str | None:
        response = ada.get(f"/api/files/{file['id']}/content")
        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        return response.headers.get("Content-Security-Policy")

    # A web page: no scripts, nothing from elsewhere, framed only by paperus.
    assert policy(page) == WEB_PAGE_POLICY
    assert "sandbox" in WEB_PAGE_POLICY and "default-src 'none'" in WEB_PAGE_POLICY
    assert "frame-ancestors 'self'" in WEB_PAGE_POLICY
    assert policy(notes) == "sandbox"
    assert policy(pdf) is None


def test_snapshots_next_to_a_pdf_go_to_the_trash(
    client: TestClient, db: Session
) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    bob = Person(client, db, "bob")
    lab_group = group(root, "Lab", ada)
    lab = ada.libraries()["Lab"]["id"]
    # Bob reads the group's papers but may change none of them.
    response = ada.put(
        f"/api/groups/{lab_group['id']}/members/{bob.id}", {"role": "reader"}
    )
    assert response.status_code in (200, 204), response.text

    with_pdf = ada.add("With a PDF")
    attach(ada, with_pdf["id"], "paper.pdf", PDF + b"a", "application/pdf")
    snapshot = attach(ada, with_pdf["id"], "2310.html", PAGE, "text/html")
    alone = ada.add("Only a web page")
    kept = attach(ada, alone["id"], "page.html", PAGE + b" ", "text/html")
    shared = ada.add("In the group", library=lab)
    attach(ada, shared["id"], "shared.pdf", PDF + b"b", "application/pdf")
    attach(ada, shared["id"], "shared.html", PAGE + b"  ", "text/html")

    def count(person: Person) -> int:
        snapshots: int = person.get("/api/manage/counts").json()["snapshots"]
        return snapshots

    assert count(ada) == 2
    assert "In the group" in bob.titles()
    assert count(bob) == 0  # a reader removes nothing
    assert bob.post("/api/manage/snapshots/trash").json() == {"trashed": 0}

    assert ada.post("/api/manage/snapshots/trash").json() == {"trashed": 2}
    assert count(ada) == 0
    # The web page that is a paper's only file stays.
    item = ada.get(f"/api/items/{alone['id']}").json()
    files = [f for v in item["versions"] for f in v["files"]]
    assert [f["id"] for f in files if not f["deleted_at"]] == [kept["id"]]
    # Moved to the trash: restorable.
    restored = ada.post(f"/api/files/{snapshot['id']}/restore")
    assert restored.status_code == 200, restored.text
    assert count(ada) == 1
