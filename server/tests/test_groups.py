"""Groups, libraries and who sees and changes what."""

import hashlib
import uuid
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.auth import create_user
from tests.conftest import FakeDOIRegistry

PDF = b"%PDF-1.7\n" + b"x" * 3000 + b"\n%%EOF\n"


class Person:
    """One logged-in person, with their own token on the shared test client."""

    def __init__(
        self, client: TestClient, db: Session, name: str, *, admin: bool = False
    ) -> None:
        create_user(db, name, "secret", is_admin=admin)
        db.commit()
        token = client.post(
            "/api/auth/login", json={"username": name, "password": "secret"}
        ).json()["token"]
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}
        self.id: str = client.get("/api/auth/me", headers=self.headers).json()["id"]

    def get(self, url: str, params: dict[str, str] | None = None) -> httpx2.Response:
        return self.client.get(url, headers=self.headers, params=params)

    def post(
        self,
        url: str,
        json: object = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> httpx2.Response:
        return self.client.post(url, headers=self.headers, json=json, files=files)

    def put(self, url: str, json: object) -> httpx2.Response:
        return self.client.put(url, headers=self.headers, json=json)

    def delete(self, url: str) -> httpx2.Response:
        return self.client.delete(url, headers=self.headers)

    def libraries(self) -> dict[str, dict[str, Any]]:
        return {lib["name"]: lib for lib in self.get("/api/libraries").json()}

    def add(self, title: str, library: str | None = None) -> dict[str, Any]:
        response = self.post(
            "/api/items", json={"metadata": {"title": title}, "library_id": library}
        )
        assert response.status_code == 201, response.text
        result: dict[str, Any] = response.json()
        return result

    def titles(self, **params: str) -> list[str]:
        return sorted(i["title"] for i in self.get("/api/items", params=params).json())


def group(
    admin: Person, name: str, first_admin: Person, parent: str | None = None
) -> dict[str, Any]:
    response = admin.post(
        "/api/groups",
        json={"name": name, "parent_id": parent, "admin_id": first_admin.id},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_private_libraries_stay_private(client: TestClient, db: Session) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    root = Person(client, db, "root", admin=True)
    secret = ada.add("Ada's draft")
    file = ada.post(
        f"/api/items/{secret['id']}/files",
        files={"upload": ("draft.pdf", PDF, "application/pdf")},
    ).json()
    ada.post(f"/api/items/{secret['id']}/tags", json={"name": "mine"})
    ada.post("/api/collections", json={"name": "Thesis"})

    assert ada.titles() == ["Ada's draft"]
    for person in (bob, root):  # site administrators read no library either
        assert person.titles() == []
        assert person.get(f"/api/items/{secret['id']}").status_code == 404
        assert person.get(f"/api/files/{file['id']}/content").status_code == 404
        assert person.get("/api/tags").json() == []
        assert person.get("/api/collections").json() == []
        assert person.get("/api/search", params={"q": "draft"}).json() == []
        assert person.delete(f"/api/items/{secret['id']}").status_code == 404
        # Nor can anyone learn that a file exists elsewhere by its hash.
        digest = hashlib.sha256(PDF).hexdigest()
        assert person.get(f"/api/uploads/{digest}").status_code == 404
        # Uploading the same file makes their own item.
        mine = person.post(
            "/api/uploads", files={"upload": ("copy.pdf", PDF, "application/pdf")}
        ).json()
        assert mine["existing"] is False
        assert mine["item_id"] != secret["id"]


def test_group_roles(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob, eve = (Person(client, db, n) for n in ("ada", "bob", "eve"))
    chair = group(root, "Chair", ada)
    library = chair["library_id"]
    paper = ada.add("Group paper", library)
    assert bob.titles() == []

    # A reader reads and searches, but changes nothing of the group's.
    assert (
        ada.put(
            f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"}
        ).status_code
        == 200
    )
    assert bob.titles() == ["Group paper"]
    assert bob.libraries()["Chair"]["writable"] is False
    assert bob.delete(f"/api/items/{paper['id']}").status_code == 403
    assert (
        bob.post(
            "/api/items", json={"metadata": {"title": "x"}, "library_id": library}
        ).status_code
        == 403
    )
    assert (
        bob.post(
            "/api/tags", json={"name": "group tag", "library_id": library}
        ).status_code
        == 403
    )
    # Their tag on a group paper is private: theirs, invisible to others.
    tags = bob.post(f"/api/items/{paper['id']}/tags", json={"name": "to read"}).json()
    assert [t["name"] for t in tags] == ["to read"]
    assert ada.get(f"/api/items/{paper['id']}").json()["tags"] == []
    assert [t["name"] for t in ada.get("/api/tags").json()] == []
    # Same for a private collection of group papers.
    shelf = bob.post("/api/collections", json={"name": "Shelf"}).json()
    bob.post(f"/api/collections/{shelf['id']}/items", json={"item_ids": [paper["id"]]})
    assert bob.titles(collection=shelf["id"]) == ["Group paper"]
    assert ada.get(f"/api/items/{paper['id']}").json()["collection_ids"] == []

    # A member changes the group's library.
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "member"})
    bob.add("Bob's find", library)
    assert ada.titles() == ["Bob's find", "Group paper"]
    group_tags = bob.post(
        f"/api/items/{paper['id']}/tags",
        json={"name": "method", "library_id": library},
    ).json()
    assert {t["name"] for t in group_tags} == {"method", "to read"}
    assert [t["name"] for t in ada.get(f"/api/items/{paper['id']}").json()["tags"]] == [
        "method"
    ]
    # A group's collection holds only the group's items.
    own = bob.add("Bob's private paper")
    reading = bob.post(
        "/api/collections", json={"name": "Reading", "library_id": library}
    ).json()
    bob.post(
        f"/api/collections/{reading['id']}/items",
        json={"item_ids": [own["id"], paper["id"]]},
    )
    assert ada.titles(collection=reading["id"]) == ["Group paper"]
    # Only admins manage members; nobody else sees the group.
    assert (
        bob.put(
            f"/api/groups/{chair['id']}/members/{eve.id}", json={"role": "reader"}
        ).status_code
        == 403
    )
    assert eve.get(f"/api/groups/{chair['id']}/members").status_code == 404
    assert eve.get("/api/groups").json() == []


def test_nested_groups_inherit_downwards(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob, cid = (Person(client, db, n) for n in ("ada", "bob", "cid"))
    chair = group(root, "Chair", ada)
    # The chair's admin creates a project inside it.
    response = ada.post(
        "/api/groups", json={"name": "Project", "parent_id": chair["id"]}
    )
    assert response.status_code == 201
    project = response.json()
    assert project["role"] == "admin"
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    ada.put(f"/api/groups/{project['id']}/members/{cid.id}", json={"role": "member"})
    ada.add("Chair paper", chair["library_id"])
    cid.add("Project paper", project["library_id"])

    # Membership goes down: the chair's reader reads the project too.
    assert bob.titles() == ["Chair paper", "Project paper"]
    assert bob.libraries()["Project"]["path"] == ["Chair"]
    # Not up: the project's member does not see the chair's library.
    assert cid.titles() == ["Project paper"]
    assert "Chair" not in cid.libraries()
    # A subgroup can raise a role.
    ada.put(f"/api/groups/{project['id']}/members/{bob.id}", json={"role": "member"})
    assert bob.libraries()["Project"]["writable"] is True
    assert bob.libraries()["Chair"]["writable"] is False

    members = {
        m["username"]: m for m in ada.get(f"/api/groups/{project['id']}/members").json()
    }
    assert members["ada"]["role"] == "admin"
    assert members["ada"]["inherited_from"] == "Chair"
    assert members["bob"]["role"] == "member"
    assert members["bob"]["inherited_from"] is None
    assert members["cid"]["direct_role"] == "member"

    # Groups with items or subgroups are not deleted.
    assert ada.delete(f"/api/groups/{chair['id']}").status_code == 409
    assert ada.delete(f"/api/groups/{project['id']}").status_code == 409


def test_creating_groups_and_keeping_an_admin(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    assert ada.post("/api/groups", json={"name": "Mine"}).status_code == 403
    assert ada.get("/api/users").status_code == 403
    chair = group(root, "Chair", ada)
    assert [u["username"] for u in ada.get("/api/users", params={"q": "b"}).json()] == [
        "bob"
    ]
    # The only admin of a top-level group cannot leave or step down.
    assert ada.delete(f"/api/groups/{chair['id']}/members/{ada.id}").status_code == 409
    assert (
        ada.put(
            f"/api/groups/{chair['id']}/members/{ada.id}", json={"role": "member"}
        ).status_code
        == 409
    )
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "admin"})
    assert ada.delete(f"/api/groups/{chair['id']}/members/{ada.id}").status_code == 200
    assert ada.titles() == []
    # Site administrators manage groups they are not in, without reading them.
    listed = root.get("/api/groups").json()
    assert [(g["name"], g["role"], g["items"]) for g in listed] == [
        ("Chair", None, None)
    ]
    assert root.delete(f"/api/groups/{chair['id']}").status_code == 204


def test_default_library_and_duplicates_per_library(
    client: TestClient, db: Session, doi_registry: FakeDOIRegistry
) -> None:
    doi_registry.records["10.1234/x"] = {"type": "journal-article", "title": "X"}
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    chair = group(root, "Chair", ada)
    assert ada.libraries()["My library"]["default"] is True
    mine = ada.post("/api/items", json={"doi": "10.1234/x"}).json()
    assert (
        ada.put(
            "/api/me/default-library", json={"library_id": chair["library_id"]}
        ).status_code
        == 204
    )
    assert ada.libraries()["Chair"]["default"] is True
    # The same DOI in another library is another item there.
    theirs = ada.post("/api/items", json={"doi": "10.1234/x"})
    assert theirs.status_code == 201
    assert theirs.json()["library_id"] == chair["library_id"]
    assert theirs.json()["id"] != mine["id"]
    # In the same library it is found again.
    again = ada.post("/api/items", json={"doi": "10.1234/x"})
    assert again.status_code == 200
    assert again.json()["id"] == theirs.json()["id"]
    # Libraries one cannot read are not targets.
    other = uuid.uuid4()
    assert (
        ada.put("/api/me/default-library", json={"library_id": str(other)}).status_code
        == 404
    )
