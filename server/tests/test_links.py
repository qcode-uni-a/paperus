"""A paper's links to its code, data and more; files of those kinds."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.people import Person, group


def link(person: Person, item: dict[str, Any], **body: object) -> dict[str, Any]:
    response = person.post(f"/api/items/{item['id']}/links", json=body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def test_links_added_updated_and_removed(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Spin qubits")
    assert ada.get(f"/api/items/{paper['id']}").json()["links"] == []

    link(ada, paper, url="https://github.com/ada/qubits", kind="code")
    link(ada, paper, url="https://doi.org/10.5281/zenodo.1234", kind="data")
    detail = link(
        ada, paper, url="https://example.org/talk", label="The talk at APS March"
    )
    assert detail["links"] == [
        {"url": "https://github.com/ada/qubits", "kind": "code", "label": None},
        {"url": "https://doi.org/10.5281/zenodo.1234", "kind": "data", "label": None},
        {
            "url": "https://example.org/talk",
            "kind": "other",
            "label": "The talk at APS March",
        },
    ]
    # The same address again (a slash more): the one there, updated.
    detail = link(
        ada, paper, url="https://github.com/ada/qubits/", kind="code", label="Code"
    )
    assert len(detail["links"]) == 3
    assert detail["links"][0]["label"] == "Code"
    # A guess (the browser extension's) leaves a person's choice alone.
    detail = link(
        ada, paper, url="http://github.com/ada/qubits", kind="data", replace=False
    )
    assert detail["links"][0] == {
        "url": "https://github.com/ada/qubits",
        "kind": "code",
        "label": "Code",
    }

    removed = ada.client.delete(
        f"/api/items/{paper['id']}/links",
        params={"url": "https://example.org/talk"},
        headers=ada.headers,
    )
    assert removed.status_code == 200, removed.text
    assert [entry["kind"] for entry in removed.json()["links"]] == ["code", "data"]
    again = ada.client.delete(
        f"/api/items/{paper['id']}/links",
        params={"url": "https://example.org/talk"},
        headers=ada.headers,
    )
    assert again.status_code == 404


def test_links_are_web_addresses(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Spin qubits")
    for body in (
        {"url": "javascript:alert(1)"},
        {"url": "github.com/ada/qubits"},
        {"url": "https://github.com/ada/qubits", "kind": "film"},
        {"url": "https://x.org/" + "a" * 2000},
    ):
        response = ada.post(f"/api/items/{paper['id']}/links", json=body)
        assert response.status_code == 422, body


def test_readers_cannot_change_links(client: TestClient, db: Session) -> None:
    root, ada = Person(client, db, "root", admin=True), Person(client, db, "ada")
    bob = Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", json={"role": "reader"})
    paper = ada.add("Spin qubits", ada.libraries()["Lab"]["id"])
    link(ada, paper, url="https://github.com/lab/qubits", kind="code")

    assert bob.get(f"/api/items/{paper['id']}").json()["links"][0]["kind"] == "code"
    response = bob.post(
        f"/api/items/{paper['id']}/links", json={"url": "https://x.org"}
    )
    assert response.status_code == 403
    carol = Person(client, db, "carol")
    response = carol.post(
        f"/api/items/{paper['id']}/links", json={"url": "https://x.org"}
    )
    assert response.status_code == 404


def test_a_merge_keeps_both_papers_links(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    keep, away = ada.add("Spin qubits"), ada.add("Spin qubits (preprint)")
    link(ada, keep, url="https://github.com/ada/qubits", kind="code")
    link(ada, away, url="https://github.com/ada/qubits", kind="code")
    link(ada, away, url="https://zenodo.org/records/1234", kind="data")

    merged = ada.post(f"/api/items/{away['id']}/merge", json={"into": keep["id"]})
    assert merged.status_code == 200, merged.text
    links = ada.get(f"/api/items/{keep['id']}").json()["links"]
    assert [entry["url"] for entry in links] == [
        "https://github.com/ada/qubits",
        "https://zenodo.org/records/1234",
    ]


def test_code_and_data_files(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Spin qubits")
    for name, role, data in (
        ("analysis.py", "code", b"x = 1\n"),
        ("counts.csv", "data", b"x,1\n"),
    ):
        response = ada.client.post(
            f"/api/items/{paper['id']}/files",
            headers=ada.headers,
            files={"upload": (name, data, "text/plain")},
            data={"role": role},
        )
        assert response.status_code == 201, response.text
        assert response.json()["role"] == role


def test_the_same_file_twice_is_kept_once(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Spin qubits")
    ids = set()
    for _ in range(2):
        response = ada.client.post(
            f"/api/items/{paper['id']}/files",
            headers=ada.headers,
            files={"upload": ("si.zip", b"PK\x03\x04 data", "application/zip")},
            data={"role": "supplementary"},
        )
        assert response.status_code == 201, response.text
        ids.add(response.json()["id"])
    assert len(ids) == 1
    files = ada.get(f"/api/items/{paper['id']}").json()["versions"][0]["files"]
    assert [f["filename"] for f in files] == ["si.zip"]
