"""Sharing with single people (#16): small groups of people ("Anna & Ben"),
made by anyone, all equal."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.people import Person


def test_a_group_of_people_made_and_found_again(
    client: TestClient, db: Session
) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    carl = Person(client, db, "carl")
    # Anyone finds people by name (from two letters on), not a list of all.
    assert [
        u["username"] for u in carl.get("/api/users", params={"q": "bo"}).json()
    ] == ["bob"]
    assert carl.get("/api/users").status_code == 403

    made = ada.post("/api/groups/people", {"user_ids": [bob.id]})
    assert made.status_code == 200, made.text
    group = made.json()
    assert (group["name"], group["people"], group["role"]) == (
        "ada & bob",
        True,
        "admin",
    )
    # The same people: the same group, whoever asks.
    again = bob.post("/api/groups/people", {"user_ids": [ada.id]}).json()
    assert again["id"] == group["id"]
    members = ada.get(f"/api/groups/{group['id']}/members").json()
    assert {(m["username"], m["role"]) for m in members} == {
        ("ada", "admin"),
        ("bob", "admin"),
    }
    # Shown as such among one's libraries.
    library = next(
        lib
        for lib in bob.get("/api/libraries").json()
        if lib["id"] == group["library_id"]
    )
    assert (library["name"], library["people"]) == ("ada & bob", True)

    # A paper shared there: bob sees it, carl does not.
    paper = ada.add("Rain gauges")
    shared = ada.put(
        f"/api/items/{paper['id']}/owner", {"library_id": group["library_id"]}
    )
    assert shared.status_code == 200, shared.text
    assert "Rain gauges" in bob.titles()
    assert "Rain gauges" not in carl.titles()

    # Three people: a group of their own, named after all of them.
    three = ada.post("/api/groups/people", {"user_ids": [bob.id, carl.id]}).json()
    assert three["id"] != group["id"] and three["name"] == "ada, bob & carl"


def test_all_equal_and_no_groups_inside(client: TestClient, db: Session) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    carl = Person(client, db, "carl")
    group = ada.post("/api/groups/people", {"user_ids": [bob.id]}).json()
    # bob adds carl, even "as a reader": an equal all the same.
    added = bob.put(f"/api/groups/{group['id']}/members/{carl.id}", {"role": "reader"})
    assert added.status_code == 200, added.text
    assert {m["username"]: m["role"] for m in added.json()}["carl"] == "admin"
    # Renamed by any of them.
    renamed = carl.patch(f"/api/groups/{group['id']}", {"name": "Rain project"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Rain project"
    inside = ada.post("/api/groups", {"name": "Sub", "parent_id": group["id"]})
    assert inside.status_code == 409

    # Not with oneself alone, nor with someone gone.
    assert ada.post("/api/groups/people", {"user_ids": [ada.id]}).status_code == 422
    unknown = "00000000-0000-0000-0000-000000000000"
    assert ada.post("/api/groups/people", {"user_ids": [unknown]}).status_code == 404
