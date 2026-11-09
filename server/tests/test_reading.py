"""Where a person stopped reading a paper (``/api/items/{id}/reading``)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.people import Person, group

PDF = b"%PDF-1.7\n" + b"x" * 3000 + b"\n%%EOF\n"


def test_each_person_goes_on_where_they_stopped(
    client: TestClient, db: Session
) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", json={"role": "reader"})
    paper = ada.add("Shared paper", lab["library_id"])["id"]
    file = ada.post(
        f"/api/items/{paper}/files",
        files={"upload": ("paper.pdf", PDF, "application/pdf")},
    ).json()["id"]

    assert ada.get(f"/api/items/{paper}/reading").json() is None
    place = {"file_id": file, "page": 4, "top": 312.5, "left": 306.0}
    assert ada.put(f"/api/items/{paper}/reading", place).status_code == 204
    assert ada.get(f"/api/items/{paper}/reading").json() == place
    # Further on, from normal mode (no column known).
    later = {"file_id": file, "page": 6, "top": 40.0, "left": None}
    ada.put(f"/api/items/{paper}/reading", later)
    assert ada.get(f"/api/items/{paper}/reading").json() == later
    # Opening it again keeps the place; it is Ada's, not Bob's.
    ada.post(f"/api/items/{paper}/viewed")
    assert ada.get(f"/api/items/{paper}/reading").json() == later
    assert bob.get(f"/api/items/{paper}/reading").json() is None


def test_only_its_own_files_and_papers_one_sees(
    client: TestClient, db: Session
) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    paper = ada.add("Ada's paper")["id"]
    other = ada.add("Another paper")["id"]
    file = ada.post(
        f"/api/items/{other}/files",
        files={"upload": ("other.pdf", PDF, "application/pdf")},
    ).json()["id"]
    place = {"file_id": file, "page": 1, "top": 0}
    assert ada.put(f"/api/items/{paper}/reading", place).status_code == 404
    assert bob.put(f"/api/items/{other}/reading", place).status_code == 404
    assert bob.get(f"/api/items/{other}/reading").status_code == 404
