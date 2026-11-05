"""Users settings: groups new accounts join, and handing a departed
person's things to a group or another person."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus.models import Membership, User
from tests.people import Person, group


def test_hand_over_to_a_group(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    ben = Person(client, db, "ben")
    chair = group(root, "Chair", ben)
    chair_library = chair["library_id"]

    ours = ben.add("Group paper", library=chair_library)
    ben.post("/api/tags", json={"name": "rain", "library_id": chair_library})
    mine = ada.add("Ada's paper")
    ada.post(f"/api/items/{mine['id']}/tags", json={"name": "Rain"})
    ada.post(f"/api/items/{mine['id']}/tags", json={"name": "Thesis"})
    ada.note("Ada's note", items=[mine["id"]])
    shelf = ada.post("/api/collections", json={"name": "Reading"}).json()
    ada.post(f"/api/collections/{shelf['id']}/items", json={"item_ids": [mine["id"]]})

    leaving = root.get(f"/api/admin/users/{ada.id}/private").json()
    assert leaving == {"items": 1, "notes": 1, "tags": 2, "collections": 1}
    # Only once deactivated.
    early = root.post(
        f"/api/admin/users/{ada.id}/hand-over", json={"group_id": chair["id"]}
    )
    assert early.status_code == 409
    root.patch(f"/api/admin/users/{ada.id}", json={"active": False})
    done = root.post(
        f"/api/admin/users/{ada.id}/hand-over", json={"group_id": chair["id"]}
    )
    assert done.status_code == 200, done.text
    assert done.json() == leaving
    assert root.get(f"/api/admin/users/{ada.id}/private").json() == {
        "items": 0,
        "notes": 0,
        "tags": 0,
        "collections": 0,
    }

    # Ben sees it all in the group, with "Rain" merged into "rain".
    assert ben.titles() == ["Ada's paper", "Group paper"]
    tags = {t["name"]: t for t in ben.get("/api/tags").json()}
    assert "Rain" not in tags
    assert {"rain", "Thesis"} <= set(tags)
    detail = ben.get(f"/api/items/{mine['id']}").json()
    assert sorted(t["name"] for t in detail["tags"]) == ["Thesis", "rain"]
    collections = {c["name"]: c for c in ben.get("/api/collections").json()}
    assert collections["Reading"]["library_id"] == chair_library
    notes = ben.get("/api/notes").json()
    assert [n["title"] for n in notes] == ["Ada's note"]
    assert ours["id"] != mine["id"]


def test_hand_over_to_a_person(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    ben = Person(client, db, "ben")
    ada.add("Ada's paper")
    root.patch(f"/api/admin/users/{ada.id}", json={"active": False})
    assert root.post(f"/api/admin/users/{ada.id}/hand-over", json={}).status_code == 422
    assert (
        root.post(
            f"/api/admin/users/{ada.id}/hand-over", json={"user_id": ada.id}
        ).status_code
        == 422
    )
    done = root.post(f"/api/admin/users/{ada.id}/hand-over", json={"user_id": ben.id})
    assert done.json()["items"] == 1
    assert ben.titles() == ["Ada's paper"]


def test_new_accounts_join_groups(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ben = Person(client, db, "ben")
    chair = group(root, "Chair", ben)
    config = root.get("/api/admin/config").json()
    config["new_user_groups"] = [{"group_id": chair["id"], "role": "reader"}]
    assert root.put("/api/admin/config", json=config).status_code == 200

    made = root.post(
        "/api/admin/users", json={"username": "cy", "password": "password1"}
    )
    assert made.status_code == 201
    cy = db.scalar(select(User).where(User.username == "cy"))
    assert cy is not None
    role = db.scalar(select(Membership.role).where(Membership.user_id == cy.id))
    assert role == "reader"
