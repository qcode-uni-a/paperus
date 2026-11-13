"""Automations (``paperus.automations``, ``/api/automations``) and papers
added by their authors' ORCID iDs (``paperus.own_papers``)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import automations, missing, own_papers
from paperus.jobs import _open_access_wanted
from paperus.models import Item, Library, User
from tests.people import Person, group

ORCID = "0000-0002-1825-0097"


def openalex_and_doi(works: list[str], records: dict[str, Any]) -> httpx2.Client:
    """OpenAlex lists these DOIs as the person's; doi.org knows ``records``."""

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.openalex.org":
            return httpx2.Response(
                200,
                json={
                    "results": [
                        {"doi": f"https://doi.org/{d}", "title": d, "type": "article"}
                        for d in works
                    ]
                },
            )
        doi = request.url.path.removeprefix("/")
        if doi in records:
            return httpx2.Response(200, json=records[doi])
        return httpx2.Response(404)

    return httpx2.Client(transport=httpx2.MockTransport(answer))


def csl(title: str, days_ago: int) -> dict[str, Any]:
    day = datetime.now(UTC).date() - timedelta(days=days_ago)
    return {
        "type": "article-journal",
        "title": title,
        "container-title": "Phys. Rev. B",
        "issued": {"date-parts": [[day.year, day.month, day.day]]},
        "author": [{"family": "Lovelace", "given": "Ada", "ORCID": ORCID}],
    }


def with_orcid(db: Session, person: Person) -> None:
    user = db.get(User, uuid.UUID(person.id))
    assert user is not None
    user.orcid = ORCID
    db.commit()


def with_doi(person: Person, title: str, doi: str, library: str | None = None) -> str:
    response = person.post(
        "/api/items",
        {
            "metadata": {"title": title},
            "identifiers": [{"scheme": "doi", "value": doi}],
            "library_id": library,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def library_of(db: Session, library_id: str) -> Library:
    db.expire_all()
    library = db.get(Library, uuid.UUID(library_id))
    assert library is not None
    return library


def titles(db: Session, library_id: str) -> list[str]:
    return sorted(
        db.scalars(
            select(Item.title).where(
                Item.library_id == uuid.UUID(library_id), Item.deleted_at.is_(None)
            )
        )
    )


def test_ones_papers_added_once(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    with_orcid(db, ada)
    own = ada.libraries()["Me"]["id"]
    # In her trash already: never added again.
    gone = with_doi(ada, "Gone", "10.1000/gone")
    ada.delete(f"/api/items/{gone}")
    http = openalex_and_doi(
        ["10.1000/new", "10.1000/old", "10.1000/gone", "10.1000/unknown"],
        {"10.1000/new": csl("New hail", 2), "10.1000/old": csl("Old hail", 400)},
    )
    added = own_papers.add_new(db, http, library_of(db, own))
    assert titles(db, own) == ["New hail", "Old hail"]
    assert all(item.added_by == uuid.UUID(ada.id) for item in added)
    notices = ada.get("/api/me/notifications").json()["notifications"]
    kinds = sorted((n["kind"], n["data"].get("count")) for n in notices)
    # Told what was added; the paper out two days ago celebrated.
    assert kinds == [("own_added", 2), ("published", None)]
    assert library_of(db, own).own_papers_seen == sorted(
        ["10.1000/gone", "10.1000/new", "10.1000/old", "10.1000/unknown"]
    )

    # Removed: stays removed.
    new = next(item for item in added if item.title == "New hail")
    ada.delete(f"/api/items/{new.id}")
    assert own_papers.add_new(db, http, library_of(db, own)) == []
    assert titles(db, own) == ["Old hail"]


def test_switches_per_library(client: TestClient, db: Session, job_app: App) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob, eve = (Person(client, db, n) for n in ("ada", "bob", "eve"))
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", {"role": "member"})
    ada.put(f"/api/groups/{lab['id']}/members/{eve.id}", {"role": "reader"})
    found = bob.get("/api/automations").json()
    assert found["server"]["find_published"] is True
    own, theirs = found["libraries"]
    assert own == {
        "library_id": bob.libraries()["Me"]["id"],
        "own_papers": True,
        "open_access": True,
        "can_change": True,
    }
    assert theirs == {
        "library_id": lab["library_id"],
        "own_papers": False,
        "open_access": True,
        "can_change": False,
    }
    url = f"/api/libraries/{lab['library_id']}/automations"
    assert bob.put(url, {"own_papers": True}).status_code == 403
    assert (
        root.put(f"/api/libraries/{own['library_id']}/automations", {}).status_code
        == 404
    )
    switched = ada.put(url, {"own_papers": True, "open_access": False})
    assert switched.status_code == 200, switched.text
    assert switched.json()["own_papers"] is True
    assert isinstance(job_app.connector, InMemoryConnector)
    assert any(
        job["task_name"] == "paperus:add_own_papers"
        and job["args"].get("library_id") == lab["library_id"]
        for job in job_app.connector.jobs.values()
    )
    assert uuid.UUID(lab["library_id"]) in {lib.id for lib in own_papers.waiting(db)}

    # The members who may add papers, with ORCID iDs: theirs come in.
    for person in (bob, eve):
        with_orcid(db, person)
    assert [u.id for u in own_papers.people(db, library_of(db, lab["library_id"]))] == [
        uuid.UUID(bob.id)
    ]
    # Open-access copies: not for the group's papers now, neither when a
    # published version is found nor in the sweep (whose query leaves them
    # out, so they cannot hold up everyone else's).
    paper = with_doi(ada, "Rain", "10.1000/rain", library=lab["library_id"])
    mine = with_doi(ada, "Snow", "10.1000/snow")
    wanted = _open_access_wanted(
        db, [(uuid.UUID(paper), None), (uuid.UUID(mine), None)]
    )
    assert wanted == [(uuid.UUID(mine), None)]
    soon = datetime.now(UTC) + timedelta(minutes=1)
    waiting = missing.never_tried(
        db,
        added_before=soon,
        limit=10,
        libraries=automations.libraries_with(db, "open_access"),
    )
    assert [item_id for item_id, _ in waiting] == [uuid.UUID(mine)]


def test_a_group_first(client: TestClient, db: Session) -> None:
    """Wanted by a group and by its member: in the group, not twice."""
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    lab = group(root, "Lab", ada)
    with_orcid(db, ada)
    ada.put(f"/api/libraries/{lab['library_id']}/automations", {"own_papers": True})
    http = openalex_and_doi(["10.1000/new"], {"10.1000/new": csl("New hail", 2)})
    for library in own_papers.waiting(db):
        own_papers.add_new(db, http, library)
    assert titles(db, lab["library_id"]) == ["New hail"]
    assert titles(db, ada.libraries()["Me"]["id"]) == []
