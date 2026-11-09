"""Notifications (``paperus.notifications``, ``/api/me/notifications``)."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import notifications
from paperus.models import Item, Notification
from tests.people import Person, group


def listed(person: Person) -> dict:
    response = person.get("/api/me/notifications")
    assert response.status_code == 200, response.text
    return response.json()


def test_papers_added_to_a_group(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", json={"role": "member"})
    first = ada.add("Rainfall records", lab["library_id"])
    ada.add("Snowfall records", lab["library_id"])
    ada.add("Ada's own notes")  # her own library: nobody else's business

    found = listed(bob)
    assert found["unread"] == 1
    [notice] = found["notifications"]
    assert notice["kind"] == "added"
    assert notice["data"] == {
        "library_id": lab["library_id"],
        "group": "Lab",
        "actor_id": ada.id,
        "actor": "ada",
        "count": 2,
        "item_id": first["id"],
        "title": "Rainfall records",
    }
    assert listed(ada) == {"notifications": [], "unread": 0}

    # Read: the next addition is a notification of its own.
    assert (
        bob.post("/api/me/notifications/read", {"ids": [notice["id"]]}).status_code
        == 204
    )
    ada.add("Hail records", lab["library_id"])
    found = listed(bob)
    assert found["unread"] == 1
    assert [n["data"]["count"] for n in found["notifications"]] == [1, 2]
    assert [n["read"] for n in found["notifications"]] == [False, True]


def test_papers_given_to_a_group_and_groups_inside(
    client: TestClient, db: Session
) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob, eve = (Person(client, db, n) for n in ("ada", "bob", "eve"))
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", json={"role": "member"})
    team = group(ada, "Team", ada, parent=lab["id"])
    ada.put(f"/api/groups/{team['id']}/members/{eve.id}", json={"role": "member"})
    ids = [ada.add(t)["id"] for t in ("Rain", "Snow")]

    # Given to the group inside: its member and those of the group above.
    response = ada.post(
        "/api/items/bulk",
        json={
            "item_ids": ids,
            "action": {"kind": "owner", "library_id": team["library_id"]},
        },
    )
    assert response.status_code == 200, response.text
    for person in (bob, eve):
        [notice] = listed(person)["notifications"]
        assert (notice["data"]["group"], notice["data"]["count"]) == ("Team", 2)
    assert listed(ada)["unread"] == 0

    # All read at once.
    bob.post("/api/me/notifications/read", {})
    assert listed(bob)["unread"] == 0
    assert listed(eve)["unread"] == 1


def test_a_published_version_found(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Edge states of rainfall")
    item = db.get(Item, uuid.UUID(paper["id"]))
    assert item is not None
    version = item.versions[0]
    version.csl = {
        **version.csl,
        "container-title": ["Phys. Rev. B"],
        "issued": {"date-parts": [[2024, 3]]},
    }
    notifications.published(db, item, version)
    db.commit()
    [notice] = listed(ada)["notifications"]
    assert (notice["kind"], notice["data"]) == (
        "published",
        {
            "item_id": paper["id"],
            "title": "Edge states of rainfall",
            "journal": "Phys. Rev. B",
            "year": 2024,
        },
    )


def test_prune(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    now = datetime.now(UTC)
    for days, read in ((100, False), (40, True), (40, False), (5, True)):
        db.add(
            Notification(
                user_id=uuid.UUID(ada.id),
                kind="published",
                data={"title": f"{days} {read}"},
                at=now - timedelta(days=days),
                read_at=now if read else None,
            )
        )
    db.commit()
    assert notifications.prune(db, now) == 2
    db.commit()
    kept = db.scalars(select(Notification.data)).all()
    assert sorted(d["title"] for d in kept) == ["40 False", "5 True"]
