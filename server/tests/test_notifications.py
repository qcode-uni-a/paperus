"""Notifications (``paperus.notifications``, ``/api/me/notifications``)."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import item_references, notifications
from paperus.models import Item, Notification, User
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
    assert found["unread"] == 2
    [notice, joined] = found["notifications"]
    assert (joined["kind"], joined["data"]["papers"]) == ("joined", 0)
    assert notice["kind"] == "added"
    assert notice["data"] == {
        "library_id": lab["library_id"],
        "group": "Lab",
        "actor_id": ada.id,
        "actor": "ada",
        "count": 2,
        "item_id": first["id"],
        "title": "Rainfall records",
        "people": False,
    }
    # Hers: only that root made her the group's admin.
    assert [n["kind"] for n in listed(ada)["notifications"]] == ["joined"]
    bob.post("/api/me/notifications/read", {"ids": [joined["id"]]})

    # Read: the next addition is a notification of its own.
    assert (
        bob.post("/api/me/notifications/read", {"ids": [notice["id"]]}).status_code
        == 204
    )
    ada.add("Hail records", lab["library_id"])
    found = listed(bob)
    assert found["unread"] == 1
    added = [n for n in found["notifications"] if n["kind"] == "added"]
    assert [n["data"]["count"] for n in added] == [1, 2]
    assert [n["read"] for n in added] == [False, True]


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
        [notice, _] = listed(person)["notifications"]
        assert (notice["data"]["group"], notice["data"]["count"]) == ("Team", 2)
    assert [n["kind"] for n in listed(ada)["notifications"]] == ["joined"]

    # All read at once.
    bob.post("/api/me/notifications/read", {})
    assert listed(bob)["unread"] == 0
    assert listed(eve)["unread"] == 2


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


def test_ones_own_paper_published(client: TestClient, db: Session) -> None:
    """Among its authors by one's ORCID iD (here from the published
    version's author list): told as one's own paper."""
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", {"role": "member"})
    paper = ada.add("Hail on qubits", lab["library_id"])
    user = db.get(User, uuid.UUID(ada.id))
    assert user is not None
    user.orcid = "0000-0002-1825-0097"
    item = db.get(Item, uuid.UUID(paper["id"]))
    assert item is not None
    version = item.versions[0]
    version.csl = {
        **version.csl,
        "author": [
            {
                "family": "Lovelace",
                "given": "Ada",
                "ORCID": "https://orcid.org/0000-0002-1825-0097",
            },
            {"family": "Babbage", "given": "Charles"},
        ],
    }
    notifications.published(db, item, version)
    db.commit()

    def published(person: Person) -> dict:
        [notice] = [
            n for n in listed(person)["notifications"] if n["kind"] == "published"
        ]
        return notice["data"]

    assert published(ada)["yours"] is True
    assert "yours" not in published(bob)


def test_ones_own_fresh_paper_added(client: TestClient, db: Session) -> None:
    """One's own paper added less than a week after it came out, by
    anyone (oneself too): celebrated, once a paper."""
    ada = Person(client, db, "ada")
    user = db.get(User, uuid.UUID(ada.id))
    assert user is not None
    user.orcid = "0000-0002-1825-0097"
    db.commit()

    def add(title: str, days: int) -> str:
        day = datetime.now(UTC).date() - timedelta(days=days)
        metadata = {
            "title": title,
            "container-title": "Phys. Rev. Lett.",
            "issued": {"date-parts": [[day.year, day.month, day.day]]},
            "author": [
                {"family": "Lovelace", "given": "Ada", "ORCID": "0000-0002-1825-0097"}
            ],
        }
        response = ada.post("/api/items", {"metadata": metadata})
        assert response.status_code == 201, response.text
        return response.json()["id"]

    fresh = add("Hail on qubits", 2)
    add("Old hail", 30)
    [notice] = listed(ada)["notifications"]
    assert notice["kind"] == "published"
    assert notice["data"] == {
        "item_id": fresh,
        "title": "Hail on qubits",
        "journal": "Phys. Rev. Lett.",
        "year": (datetime.now(UTC).date() - timedelta(days=2)).year,
        "yours": True,
        "fresh": True,
    }
    # Found published again later: not twice.
    item = db.get(Item, uuid.UUID(fresh))
    assert item is not None
    notifications.published(db, item, item.versions[0])
    db.commit()
    published = [n for n in listed(ada)["notifications"] if n["data"].get("yours")]
    assert len(published) == 1


def test_ones_paper_cited(client: TestClient, db: Session) -> None:
    """A paper new in the library citing one's own: celebrated, once, to
    those of its authors who can read both; not one's own citing it."""
    root = Person(client, db, "root", admin=True)
    ada, bob, eve = (Person(client, db, n) for n in ("ada", "bob", "eve"))
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", {"role": "member"})
    orcid = "0000-0002-1825-0097"
    user = db.get(User, uuid.UUID(ada.id))
    assert user is not None
    user.orcid = orcid
    db.commit()

    def paper(
        person: Person, title: str, doi: str, library: str | None, *ids: str
    ) -> str:
        metadata = {
            "title": title,
            "author": [{"family": "X", "given": "Y", "ORCID": i} for i in ids],
        }
        response = person.post(
            "/api/items",
            {
                "metadata": metadata,
                "identifiers": [{"scheme": "doi", "value": doi}],
                "library_id": library,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    hers = paper(ada, "Hail on qubits", "10.1000/hail", lab["library_id"], orcid)
    citing = paper(bob, "More hail", "10.1000/more", lab["library_id"])
    elsewhere = paper(eve, "Hail elsewhere", "10.1000/else", None)
    own = paper(ada, "My hail again", "10.1000/again", lab["library_id"], orcid)
    cites = [item_references.Found("Hail on qubits", doi="10.1000/hail")]
    for item_id in (citing, elsewhere, own, citing):  # the first twice
        item_references.store(db, uuid.UUID(item_id), "crossref", cites)
    [notice] = [n for n in listed(ada)["notifications"] if n["kind"] == "cited"]
    assert (notice["kind"], notice["data"]) == (
        "cited",
        {
            "item_id": citing,
            "title": "More hail",
            "cited_id": hers,
            "cited_title": "Hail on qubits",
            "count": 1,
        },
    )


def test_a_paper_shared_with_one(client: TestClient, db: Session) -> None:
    """Shared with a person (#16): told as shared with them, once (the
    small group made for it says nothing of its own while empty)."""
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    paper = ada.add("Drizzle")
    two = ada.post("/api/groups/people", {"user_ids": [bob.id]}).json()
    assert listed(bob)["unread"] == 0
    moved = ada.put(
        f"/api/items/{paper['id']}/owner", {"library_id": two["library_id"]}
    )
    assert moved.status_code == 200, moved.text
    [notice] = listed(bob)["notifications"]
    assert notice["kind"] == "added"
    assert notice["data"]["people"] is True
    assert (notice["data"]["actor"], notice["data"]["title"]) == ("ada", "Drizzle")
    assert listed(ada)["unread"] == 0

    # Someone more in it later: told what is shared with them now.
    eve = Person(client, db, "eve")
    ada.put(f"/api/groups/{two['id']}/members/{eve.id}", {"role": "admin"})
    [joined] = listed(eve)["notifications"]
    assert joined["kind"] == "joined"
    assert {k: joined["data"][k] for k in ("people", "papers", "actor")} == {
        "people": True,
        "papers": 1,
        "actor": "ada",
    }


def test_added_to_a_group(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.add("Rain", lab["library_id"])
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", {"role": "reader"})
    [joined] = listed(bob)["notifications"]
    assert (joined["kind"], joined["data"]) == (
        "joined",
        {
            "group_id": lab["id"],
            "library_id": lab["library_id"],
            "group": "Lab",
            "people": False,
            "papers": 1,
            "actor_id": ada.id,
            "actor": "ada",
        },
    )
    # A new role is no news.
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", {"role": "member"})
    assert listed(bob)["unread"] == 1


def test_someone_added_told_to_the_admins(client: TestClient, db: Session) -> None:
    """The group's other admins are told who was added (one notice for
    people added one after another); not who added them, not the members."""
    root = Person(client, db, "root", admin=True)
    ada, eve, bob, carl = (Person(client, db, n) for n in ("ada", "eve", "bob", "carl"))
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{eve.id}", {"role": "admin"})
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", {"role": "member"})
    ada.put(f"/api/groups/{lab['id']}/members/{carl.id}", {"role": "reader"})
    added = [n for n in listed(eve)["notifications"] if n["kind"] == "member_added"]
    assert [n["data"] for n in added] == [
        {
            "group_id": lab["id"],
            "library_id": lab["library_id"],
            "group": "Lab",
            "people": False,
            "actor_id": ada.id,
            "actor": "ada",
            "members": ["bob", "carl"],
            "count": 2,
        }
    ]
    for person in (ada, bob):
        kinds = [n["kind"] for n in listed(person)["notifications"]]
        assert "member_added" not in kinds


def test_an_erratum_found(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Edge states of hail")
    item = db.get(Item, uuid.UUID(paper["id"]))
    assert item is not None
    notifications.erratum(db, item, "Erratum: Phys. Rev. B 96, 199902 (2017)")
    db.commit()
    [notice] = listed(ada)["notifications"]
    assert (notice["kind"], notice["data"]) == (
        "erratum",
        {
            "item_id": paper["id"],
            "title": "Edge states of hail",
            "erratum": "Erratum: Phys. Rev. B 96, 199902 (2017)",
        },
    )


def test_dismissed(client: TestClient, db: Session) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    for title in ("Rain", "Snow", "Hail"):
        item = db.get(Item, uuid.UUID(ada.add(title)["id"]))
        assert item is not None
        notifications.erratum(db, item, f"Erratum: {title}")
    db.commit()
    first, *rest = listed(ada)["notifications"]
    assert ada.delete(f"/api/me/notifications/{first['id']}").status_code == 204
    assert [n["id"] for n in listed(ada)["notifications"]] == [n["id"] for n in rest]
    # Only one's own.
    assert bob.delete(f"/api/me/notifications/{rest[0]['id']}").status_code == 404
    assert ada.delete(f"/api/me/notifications/{first['id']}").status_code == 404
    assert ada.delete("/api/me/notifications").status_code == 204
    assert listed(ada) == {"notifications": [], "unread": 0}


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
