"""Automations (``paperus.automations``, ``/api/automations``) and papers
added by their authors' ORCID iDs (``paperus.own_papers``)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from procrastinate import App
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import automations, missing, own_papers, published
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
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", {"role": "member"})
    found = bob.get("/api/automations").json()
    assert found["server"]["find_published"] is True
    own, theirs = found["libraries"]
    mine = bob.libraries()["Me"]["id"]
    assert own == {
        "library_id": mine,
        "published": True,
        "open_access": True,
        "own_papers": True,
        "own_papers_to": None,
        "can_change": True,
    }
    assert theirs == {
        "library_id": lab["library_id"],
        "published": True,
        "open_access": True,
        "own_papers": None,
        "own_papers_to": None,
        "can_change": False,
    }
    url = f"/api/libraries/{lab['library_id']}/automations"
    assert bob.put(url, {"published": False}).status_code == 403
    assert root.put(f"/api/libraries/{mine}/automations", {}).status_code == 404
    # Its admins only; not the site administrator, outside the group.
    assert ada.get(url).json()["can_change"] is True
    for outside in (root, Person(client, db, "eve")):
        assert outside.get(url).status_code == 404
    switched = ada.put(url, {"published": False, "open_access": False})
    assert switched.status_code == 200, switched.text
    assert (switched.json()["published"], switched.json()["own_papers"]) == (
        False,
        None,
    )

    # Off for the group: neither published versions nor open-access copies
    # looked for its papers, in the queries (they cannot hold up others').
    paper = with_doi(ada, "Rain", "10.1000/rain", library=lab["library_id"])
    other = with_doi(ada, "Snow", "10.1000/snow")
    wanted = _open_access_wanted(
        db, [(uuid.UUID(paper), None), (uuid.UUID(other), None)]
    )
    assert wanted == [(uuid.UUID(other), None)]
    soon = datetime.now(UTC) + timedelta(minutes=1)
    waiting = missing.never_tried(
        db,
        added_before=soon,
        limit=10,
        libraries=automations.libraries_with(db, "open_access"),
    )
    assert [item_id for item_id, _ in waiting] == [uuid.UUID(other)]
    for title, arxiv, library in (
        ("Rain v1", "2401.00001", lab["library_id"]),
        ("Snow v1", "2401.00002", None),
    ):
        ada.post(
            "/api/items",
            {
                "metadata": {"title": title},
                "identifiers": [{"scheme": "arxiv", "value": arxiv}],
                "library_id": library,
            },
        )
    preprints = published.waiting(
        db, 10, libraries=automations.libraries_with(db, "published")
    )
    assert [item.title for item in preprints] == ["Snow v1"]


def test_ones_papers_where_one_chooses(client: TestClient, db: Session) -> None:
    """Adding one's papers is one's own switch: where one's new papers go,
    or an owner one chooses (a group one may add papers to; else one's own
    library)."""
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    lab = group(root, "Lab", ada)
    with_orcid(db, ada)
    own = ada.libraries()["Me"]["id"]
    url = f"/api/libraries/{own}/automations"
    assert ada.put(url, {"own_papers_to": str(uuid.uuid4())}).status_code == 422
    # Groups have no such switch.
    group_url = f"/api/libraries/{lab['library_id']}/automations"
    assert ada.put(group_url, {"own_papers": True}).json()["own_papers"] is None
    assert [lib.id for lib in own_papers.waiting(db)] == [uuid.UUID(own)]
    user = db.get(User, uuid.UUID(ada.id))
    assert user is not None

    def target() -> uuid.UUID:
        db.expire_all()
        assert user is not None
        return own_papers.target(db, library_of(db, own), user)

    # Like her new papers: to the group once they go there.
    ada.put("/api/me/default-library", {"library_id": own})
    assert target() == uuid.UUID(own)
    ada.put("/api/me/default-library", {"library_id": lab["library_id"]})
    assert target() == uuid.UUID(lab["library_id"])
    # Chosen apart: her own library; then "like new papers" again.
    ada.put(url, {"own_papers_to": own})
    assert target() == uuid.UUID(own)
    assert ada.put(url, {"own_papers_to": "new papers"}).json()["own_papers_to"] is None
    assert target() == uuid.UUID(lab["library_id"])

    http = openalex_and_doi(["10.1000/new"], {"10.1000/new": csl("New hail", 2)})
    own_papers.add_new(db, http, library_of(db, own))
    assert titles(db, lab["library_id"]) == ["New hail"]
    # A reader there now (another admin keeps the group): her own library.
    eve = Person(client, db, "eve")
    ada.put(f"/api/groups/{lab['id']}/members/{eve.id}", {"role": "admin"})
    demoted = eve.put(f"/api/groups/{lab['id']}/members/{ada.id}", {"role": "reader"})
    assert demoted.status_code == 200, demoted.text
    assert target() == uuid.UUID(own)
    # Switched off: hers are not looked for.
    ada.put(url, {"own_papers": False})
    assert own_papers.waiting(db) == []


def test_a_renamed_journal_version_joins_its_preprint(
    client: TestClient, db: Session
) -> None:
    """OpenAlex lists the journal paper apart (renamed on publication):
    it becomes the preprint's published version, celebrated, not a paper
    of its own."""
    ada = Person(client, db, "ada")
    with_orcid(db, ada)
    own = ada.libraries()["Me"]["id"]
    preprint = ada.post(
        "/api/items",
        {
            "metadata": {"title": "Hail on qubits", "type": "article"},
            "identifiers": [{"scheme": "arxiv", "value": "2401.12345"}],
        },
    ).json()["id"]
    http = openalex_and_doi(
        ["10.1103/hail"], {"10.1103/hail": csl("Hail on superconducting qubits", 30)}
    )
    assert own_papers.add_new(db, http, library_of(db, own)) == []
    db.expire_all()
    item = db.get(Item, uuid.UUID(preprint))
    assert item is not None
    assert "published" in [v.kind for v in item.versions]
    assert titles(db, own) == ["Hail on superconducting qubits"]
    [notice] = ada.get("/api/me/notifications").json()["notifications"]
    assert (notice["kind"], notice["data"]["yours"]) == ("published", True)
    assert "10.1103/hail" in library_of(db, own).own_papers_seen
