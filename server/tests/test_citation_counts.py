"""How often papers are cited (``paperus.citation_counts``): counted at
OpenAlex each week, sorted by, milestones celebrated."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus import citation_counts
from paperus.models import Item, User
from tests.people import Person

ORCID = "0000-0002-1825-0097"


class FakeOpenAlex:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.asked: list[list[str]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        dois = request.url.params["filter"].removeprefix("doi:").split("|")
        self.asked.append(dois)
        results: list[dict[str, Any]] = [
            {"doi": f"https://doi.org/{d}", "cited_by_count": self.counts[d]}
            for d in dois
            if d in self.counts
        ]
        return httpx2.Response(200, json={"results": results})


def paper(person: Person, title: str, *dois: str, orcid: str | None = None) -> str:
    metadata: dict[str, Any] = {"title": title}
    if orcid:
        metadata["author"] = [{"family": "Lovelace", "given": "Ada", "ORCID": orcid}]
    response = person.post(
        "/api/items",
        {
            "metadata": metadata,
            "identifiers": [{"scheme": "doi", "value": d} for d in dois],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_counted_each_week_and_milestones(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    user = db.get(User, uuid.UUID(ada.id))
    assert user is not None
    user.orcid = ORCID
    db.commit()
    hers = paper(ada, "Hail", "10.1000/hail", "10.48550/arxiv.2401.00001", orcid=ORCID)
    other = paper(ada, "Snow", "10.1000/snow")
    paper(ada, "No DOI")
    openalex = FakeOpenAlex()
    http = httpx2.Client(transport=httpx2.MockTransport(openalex))
    openalex.counts = {
        "10.1000/hail": 8,
        "10.48550/arxiv.2401.00001": 3,
        "10.1000/snow": 1,
    }

    def run(now: datetime) -> int:
        db.expire_all()
        items = citation_counts.waiting(db, now=now)
        return citation_counts.check(db, http, items, now=now)

    change = ada.get(f"/api/items/{hers}").json()["change"]
    now = datetime.now(UTC)
    assert run(now) == 2
    assert len(openalex.asked) == 1  # one request for all their DOIs
    found = ada.get(f"/api/items/{hers}").json()
    # The highest of its DOIs' counts; not a change of the paper's own.
    assert (found["cited_by_count"], found["change"]) == (8, change)
    # The first count celebrates nothing; within a week, not counted again.
    assert ada.get("/api/me/notifications").json()["notifications"] == []
    assert run(now + timedelta(days=1)) == 0

    openalex.counts["10.1000/hail"] = 12
    assert run(now + timedelta(days=8)) == 2
    [notice] = ada.get("/api/me/notifications").json()["notifications"]
    assert (notice["kind"], notice["data"]) == (
        "milestone",
        {"item_id": hers, "title": "Hail", "milestone": 10, "count": 12},
    )
    # Once a milestone.
    item = db.get(Item, uuid.UUID(hers))
    assert item is not None
    db.expire_all()
    openalex.counts["10.1000/hail"] = 14
    run(now + timedelta(days=16))
    assert len(ada.get("/api/me/notifications").json()["notifications"]) == 1

    # Most cited first, the uncounted last.
    listed = ada.get("/api/items", params={"sort": "citations"}).json()
    assert [i["title"] for i in listed] == ["Hail", "Snow", "No DOI"]
    assert other in [i["id"] for i in listed]


def test_openalex_not_answering(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper(ada, "Hail", "10.1000/hail")
    down = httpx2.Client(transport=httpx2.MockTransport(lambda _: httpx2.Response(503)))
    assert citation_counts.check(db, down, citation_counts.waiting(db)) == 0
    # Waits for the next run.
    assert [i.title for i in citation_counts.waiting(db)] == ["Hail"]
