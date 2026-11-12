"""Code merged into its paper by mistake, split off again; code and data
attached to their paper instead of merged."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.people import Person, group

ZENODO = "10.5281/zenodo.1234"


def software(
    person: Person, title: str = "Code of Spin qubits", doi: str = ZENODO
) -> dict[str, Any]:
    """A software item with its DOI and a file, as Zenodo's would be."""
    response = person.post(
        "/api/items",
        json={
            "metadata": {"type": "software", "title": title},
            "identifiers": [{"scheme": "doi", "value": doi}],
        },
    )
    assert response.status_code == 201, response.text
    item: dict[str, Any] = response.json()
    upload = person.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("qubits.zip", b"PK\x05\x06" + b"\0" * 18, "application/zip")},
    )
    assert upload.status_code == 201, upload.text
    return item


def files_of(detail: dict[str, Any]) -> list[tuple[str, str]]:
    return sorted(
        (f["filename"], f["role"])
        for v in detail["versions"]
        for f in v["files"]
        if f["deleted_at"] is None
    )


def test_a_version_split_off(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper, code = ada.add("Spin qubits"), software(ada)
    merged = ada.post(f"/api/items/{code['id']}/merge", json={"into": paper["id"]})
    assert merged.status_code == 200, merged.text
    versions = merged.json()["item"]["versions"]
    assert len(versions) == 2
    wrong = next(v for v in versions if v["identifiers"])

    split = ada.post(f"/api/versions/{wrong['id']}/split")
    assert split.status_code == 201, split.text
    item = split.json()
    assert item["id"] not in (paper["id"], code["id"])
    assert item["title"] == "Code of Spin qubits"
    assert item["type"] == "software"
    assert item["library_id"] == paper["library_id"]
    assert item["identifiers"] == [{"scheme": "doi", "value": ZENODO}]
    assert files_of(item) == [("qubits.zip", "main")]
    left = ada.get(f"/api/items/{paper['id']}").json()
    assert len(left["versions"]) == 1
    assert left["title"] == "Spin qubits"
    assert files_of(left) == []
    # Its DOI finds it, not the paper.
    found = ada.get("/api/items/lookup", params={"id": [f"doi:{ZENODO}"]}).json()
    assert found[f"doi:{ZENODO}"] == item["id"]

    # The only version stays.
    only = ada.post(f"/api/versions/{left['versions'][0]['id']}/split")
    assert only.status_code == 409


def test_splitting_needs_the_right_to_change(client: TestClient, db: Session) -> None:
    root, ada = Person(client, db, "root", admin=True), Person(client, db, "ada")
    bob, carol = Person(client, db, "bob"), Person(client, db, "carol")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", json={"role": "reader"})
    lab_id = ada.libraries()["Lab"]["id"]
    paper = ada.add("Spin qubits", lab_id)
    version = ada.post(
        f"/api/items/{paper['id']}/versions",
        json={"metadata": {"title": "Spin qubits"}, "kind": "preprint"},
    ).json()["versions"][-1]
    assert bob.post(f"/api/versions/{version['id']}/split").status_code == 403
    assert carol.post(f"/api/versions/{version['id']}/split").status_code == 404
    trashed = ada.delete(f"/api/items/{paper['id']}")
    assert trashed.status_code == 204
    assert ada.post(f"/api/versions/{version['id']}/split").status_code == 409


def test_code_attached_to_its_paper(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper, code = ada.add("Spin qubits"), software(ada)
    response = ada.post(
        f"/api/items/{code['id']}/attach", json={"paper": paper["id"], "kind": "code"}
    )
    assert response.status_code == 200, response.text
    attached = response.json()
    assert attached["id"] == paper["id"]
    assert len(attached["versions"]) == 1
    assert attached["links"] == [
        {
            "url": f"https://doi.org/{ZENODO}",
            "kind": "code",
            "label": "Code of Spin qubits",
        }
    ]
    assert files_of(attached) == [("qubits.zip", "code")]
    assert ada.get(f"/api/items/{code['id']}").json()["deleted_at"] is not None
    # Its DOI is the paper's link now: it finds no item.
    found = ada.get("/api/items/lookup", params={"id": [f"doi:{ZENODO}"]}).json()
    assert found[f"doi:{ZENODO}"] is None

    # Data, as data; not to itself, not when trashed.
    data = software(ada, "Measurements", "10.5281/zenodo.5678")
    response = ada.post(
        f"/api/items/{data['id']}/attach", json={"paper": paper["id"], "kind": "data"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["links"][-1]["kind"] == "data"
    assert ("qubits.zip", "data") in files_of(response.json())
    other = ada.add("Other")
    itself = ada.post(f"/api/items/{other['id']}/attach", json={"paper": other["id"]})
    assert itself.status_code == 409
    again = ada.post(f"/api/items/{code['id']}/attach", json={"paper": other["id"]})
    assert again.status_code == 409  # in the trash


def test_attaching_needs_the_right_to_change_both(
    client: TestClient, db: Session
) -> None:
    root, ada = Person(client, db, "root", admin=True), Person(client, db, "ada")
    bob = Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", json={"role": "reader"})
    paper = ada.add("Spin qubits", ada.libraries()["Lab"]["id"])
    code = software(bob)
    response = bob.post(f"/api/items/{code['id']}/attach", json={"paper": paper["id"]})
    assert response.status_code == 403
    assert bob.get(f"/api/items/{code['id']}").json()["deleted_at"] is None
