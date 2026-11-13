"""Groups, libraries and who sees and changes what."""

import hashlib
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import FakeDOIRegistry
from tests.people import Person, group

PDF = b"%PDF-1.7\n" + b"x" * 3000 + b"\n%%EOF\n"


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
    # The only admin of a top-level group with papers cannot leave or step
    # down (an empty one would go with her).
    ada.add("Rain", chair["library_id"])
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
    # Site administrators see groups they are not in (how many papers), but
    # neither read nor run them.
    listed = root.get("/api/groups").json()
    assert [(g["name"], g["role"], g["items"], g["can_manage"]) for g in listed] == [
        ("Chair", None, 1, False)
    ]
    assert root.delete(f"/api/groups/{chair['id']}").status_code == 403


def test_default_owner_and_known_papers(
    client: TestClient, db: Session, doi_registry: FakeDOIRegistry
) -> None:
    doi_registry.records["10.1234/x"] = {"type": "journal-article", "title": "X"}
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    own = ada.libraries()["Me"]["id"]
    assert ada.libraries()["Me"]["default"] is True
    mine = ada.post("/api/items", json={"doi": "10.1234/x"}).json()
    assert mine["library_id"] == own
    assert (
        ada.put(
            "/api/me/default-library", json={"library_id": chair["library_id"]}
        ).status_code
        == 204
    )
    assert ada.libraries()["Chair"]["default"] is True
    assert ada.add("New")["library_id"] == chair["library_id"]
    # A paper Ada can see already is found, not added twice.
    again = ada.post("/api/items", json={"doi": "10.1234/x"})
    assert again.status_code == 200
    assert again.json()["id"] == mine["id"]
    # Someone who cannot see it gets an item of their own.
    theirs = bob.post("/api/items", json={"doi": "10.1234/x"})
    assert theirs.status_code == 201
    assert theirs.json()["id"] != mine["id"]
    other = uuid.uuid4()
    assert (
        ada.put("/api/me/default-library", json={"library_id": str(other)}).status_code
        == 404
    )


def test_sharing_and_taking_back(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob, eve = (Person(client, db, n) for n in ("ada", "bob", "eve"))
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "member"})
    ada.put(f"/api/groups/{chair['id']}/members/{eve.id}", json={"role": "reader"})
    paper = ada.add("Ada's paper")
    ada.post(f"/api/items/{paper['id']}/tags", json={"name": "private note"})
    assert bob.titles() == []

    # Sharing: the group becomes the owner.
    shared = ada.put(
        f"/api/items/{paper['id']}/owner", json={"library_id": chair["library_id"]}
    ).json()
    assert shared["library_id"] == chair["library_id"]
    assert bob.titles() == ["Ada's paper"]
    assert bob.get(f"/api/items/{paper['id']}").json()["tags"] == []
    tags = ada.get(f"/api/items/{paper['id']}").json()["tags"]
    assert [t["name"] for t in tags] == ["private note"]
    bob.post(
        f"/api/items/{paper['id']}/tags",
        json={"name": "method", "library_id": chair["library_id"]},
    )
    # Readers cannot give papers away.
    assert (
        eve.put(
            f"/api/items/{paper['id']}/owner",
            json={"library_id": eve.libraries()["Me"]["id"]},
        ).status_code
        == 403
    )
    # A member takes it for himself; the group's tag stays on it.
    taken = bob.put(
        f"/api/items/{paper['id']}/owner",
        json={"library_id": bob.libraries()["Me"]["id"]},
    ).json()
    assert [t["name"] for t in taken["tags"]] == ["method"]
    assert ada.titles() == []
    assert bob.titles() == ["Ada's paper"]


def test_moving_a_collection_to_another_library(
    client: TestClient, db: Session
) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    shared = ada.add("Group paper", chair["library_id"])
    private = ada.add("Private paper")
    thesis = ada.post("/api/collections", json={"name": "Thesis"}).json()
    chapter = ada.post(
        "/api/collections", json={"name": "Chapter 1", "parent_id": thesis["id"]}
    ).json()
    ada.post(
        f"/api/collections/{chapter['id']}/items",
        json={"item_ids": [shared["id"], private["id"]]},
    )
    assert bob.get("/api/collections").json() == []

    # A reader of the group cannot give it collections.
    response = bob.post("/api/collections", json={"name": "Bob's"})
    bob_collection = response.json()
    assert (
        bob.patch(
            f"/api/collections/{bob_collection['id']}",
            json={"library_id": chair["library_id"]},
        ).status_code
        == 403
    )

    preview = ada.get(
        f"/api/collections/{thesis['id']}/move-preview",
        params={"library": chair["library_id"]},
    ).json()
    assert preview == {"papers": 2, "not_in_library": 1}
    moved = ada.patch(
        f"/api/collections/{thesis['id']}", json={"library_id": chair["library_id"]}
    ).json()
    # The private paper leaves (a group's collection holds its papers only).
    assert moved["left_out"] == 1
    assert moved["library_id"] == chair["library_id"]
    listed = {c["name"]: c for c in bob.get("/api/collections").json()}
    assert listed["Chapter 1"]["library_id"] == chair["library_id"]
    assert listed["Chapter 1"]["parent_id"] == thesis["id"]
    assert bob.titles(collection=thesis["id"]) == ["Group paper"]
    assert ada.titles() == ["Group paper", "Private paper"]

    # And back: private collections hold any readable paper.
    back = ada.patch(
        f"/api/collections/{chapter['id']}",
        json={"library_id": ada.libraries()["Me"]["id"]},
    ).json()
    assert back["left_out"] == 0
    assert back["parent_id"] is None
    assert [c["name"] for c in bob.get("/api/collections").json()] == [
        "Bob's",
        "Thesis",
    ]


def test_group_tags_on_own_papers(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    shared = ada.add("Group paper", chair["library_id"])
    ada.post(
        f"/api/items/{shared['id']}/tags",
        json={"name": "methods", "library_id": chair["library_id"]},
    )
    # A reader uses the group's tag on his own paper, invisibly to others.
    mine = bob.add("Bob's paper")
    tags = bob.post(
        f"/api/items/{mine['id']}/tags",
        json={"name": "methods", "library_id": chair["library_id"]},
    ).json()
    assert [t["name"] for t in tags] == ["methods"]
    [tag] = [t for t in ada.get("/api/tags").json() if t["name"] == "methods"]
    assert tag["count"] == 1  # Ada does not see Bob's paper
    assert bob.titles(tag=tag["id"]) == ["Bob's paper", "Group paper"]
    # But he creates no group tags, and changes none on the group's papers.
    assert (
        bob.post(
            f"/api/items/{mine['id']}/tags",
            json={"name": "new", "library_id": chair["library_id"]},
        ).status_code
        == 403
    )
    assert (
        bob.client.delete(
            f"/api/items/{shared['id']}/tags/{tag['id']}", headers=bob.headers
        ).status_code
        == 403
    )

    # Giving a private tag to the group keeps it on every paper.
    private = ada.add("Ada's paper")
    ada.post(f"/api/items/{private['id']}/tags", json={"name": "reading"})
    [reading] = [t for t in ada.get("/api/tags").json() if t["name"] == "reading"]
    given = ada.patch(
        f"/api/tags/{reading['id']}", json={"library_id": chair["library_id"]}
    )
    assert given.json()["library_id"] == chair["library_id"]
    assert [
        t["name"] for t in ada.get(f"/api/items/{private['id']}").json()["tags"]
    ] == ["reading"]
    assert any(t["name"] == "reading" for t in bob.get("/api/tags").json())
    assert (
        bob.patch(
            f"/api/tags/{reading['id']}",
            json={"library_id": bob.libraries()["Me"]["id"]},
        ).status_code
        == 403
    )


def test_who_added_a_group_paper(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    ben = Person(client, db, "ben")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{ben.id}", {"role": "reader"})
    paper = ada.add("Radar notes", library=chair["library_id"])
    seen = ben.get(f"/api/items/{paper['id']}").json()
    assert seen["added_by"]["username"] == "ada"
    assert seen["added_by"]["avatar_url"] is None
