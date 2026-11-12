"""arXiv's versions of a preprint as versions of the paper: each PDF to its
own ("v1", "v2", by the name arXiv gives it), the newest cited unless a
published version is there."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.people import Person

ARXIV = "2401.12345"


def pdf(text: str) -> bytes:
    return b"%PDF-1.7\n" + text.encode() * 200 + b"\n%%EOF\n"


def preprint(person: Person) -> dict[str, Any]:
    response = person.post(
        "/api/items",
        json={
            "metadata": {"title": "Spin qubits", "type": "article"},
            "identifiers": [{"scheme": "arxiv", "value": ARXIV}],
        },
    )
    assert response.status_code == 201, response.text
    item: dict[str, Any] = response.json()
    return item


def upload(person: Person, item: dict[str, Any], name: str, text: str) -> None:
    response = person.post(
        f"/api/items/{item['id']}/files",
        files={"upload": (name, pdf(text), "application/pdf")},
    )
    assert response.status_code == 201, response.text


def versions(person: Person, item: dict[str, Any]) -> tuple[dict[str, list[str]], str]:
    """Each version's label and its files' names and roles; the cited one."""
    detail = person.get(f"/api/items/{item['id']}").json()
    shown = {
        v["label"] or v["kind"]: sorted(
            f"{f['filename']} {f['role']}" for f in v["files"] if not f["deleted_at"]
        )
        for v in detail["versions"]
    }
    cited = next(
        v for v in detail["versions"] if v["id"] == detail["preferred_version_id"]
    )
    return shown, cited["label"] or cited["kind"]


def test_each_arxiv_version_its_own(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    item = preprint(ada)
    upload(ada, item, f"{ARXIV}v1.pdf", "first")
    assert versions(ada, item) == ({"v1": [f"{ARXIV}v1.pdf main"]}, "v1")

    upload(ada, item, f"{ARXIV}v3.pdf", "third")
    shown, cited = versions(ada, item)
    assert shown == {
        "v1": [f"{ARXIV}v1.pdf main"],
        "v3": [f"{ARXIV}v3.pdf main"],
    }
    assert cited == "v3"
    # An older one, later: its own, the newest still cited.
    upload(ada, item, f"{ARXIV}v2.pdf", "second")
    shown, cited = versions(ada, item)
    assert list(shown) == ["v1", "v3", "v2"]
    assert cited == "v3"
    # The same file again: nothing new.
    upload(ada, item, f"{ARXIV}v2.pdf", "second")
    assert sum(len(files) for files in versions(ada, item)[0].values()) == 3
    # Looked up by its arXiv ID: this paper.
    found = ada.get("/api/items/lookup", params={"id": [f"arxiv:{ARXIV}"]}).json()
    assert found[f"arxiv:{ARXIV}"] == item["id"]

    # A published version is cited before any of arXiv's.
    published = ada.post(
        f"/api/items/{item['id']}/versions",
        json={"metadata": {"title": "Spin qubits"}, "kind": "published"},
    )
    assert published.status_code == 201, published.text
    assert versions(ada, item)[1] == "published"


def test_other_names_as_they_were(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    item = preprint(ada)
    upload(ada, item, "spin-qubits.pdf", "a copy")
    upload(ada, item, "2401.99999v2.pdf", "another paper's")
    shown, cited = versions(ada, item)
    assert shown == {"other": ["2401.99999v2.pdf main", "spin-qubits.pdf main"]}
    # A preprint with a PDF of no known version keeps it; arXiv's v2 gets
    # one of its own.
    upload(ada, item, f"{ARXIV}v2.pdf", "second")
    shown, cited = versions(ada, item)
    assert shown["v2"] == [f"{ARXIV}v2.pdf main"]
    assert cited == "v2"
