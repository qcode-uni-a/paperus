"""A person's works from OpenAlex, to add those not in the library yet."""

from typing import Any

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus import authors, works
from paperus.models import Author
from tests.people import Person
from tests.test_authors import paper, people, with_doi

ORCID = "0000-0002-1825-0097"


def openalex(entries: list[dict[str, Any]], asked: list[str]) -> httpx2.Client:
    def answer(request: httpx2.Request) -> httpx2.Response:
        asked.append(request.url.params["filter"])
        return httpx2.Response(200, json={"results": entries})

    return httpx2.Client(transport=httpx2.MockTransport(answer))


def entry(doi: str | None, title: str, **more: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "doi": f"https://doi.org/{doi}" if doi else None,
        "title": title,
        "publication_year": 2024,
        "primary_location": {"source": {"display_name": "Physical Review B"}},
        "type": "article",
    } | more


ENTRIES = [
    # A paper's arXiv copy listed first: the journal's DOI is the work's.
    entry("10.48550/arxiv.2401.1", "In the library", publication_year=2023),
    entry("10.1000/HERE", "In the Library"),
    entry("10.1000/new", "Not yet", primary_location=None, publication_year=None),
    entry("10.1000/new", "The same DOI twice"),
    entry(None, "Without a DOI"),
    entry("10.1000/erratum", "Erratum", type="erratum"),
]


def test_an_authors_works(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    here = with_doi(ada, "In the library", "10.1000/here", "Benito, Mónica")
    alone = paper(ada, "No ids", "Nobody, Ned")
    authors.link_waiting(db)
    [benito] = people(db, here)
    [ned] = people(db, alone)
    record = db.get(Author, benito)
    assert record is not None
    record.openalex_id = "A123"
    db.commit()
    asked: list[str] = []
    client.app.state.http = openalex(ENTRIES, asked)  # ty: ignore[unresolved-attribute]

    found = ada.get(f"/api/authors/{benito}/works").json()
    assert [(w["doi"], w["item_id"]) for w in found] == [
        ("10.1000/here", here),
        ("10.1000/new", None),
    ]
    http = openalex(ENTRIES, [])
    [first, _] = works.works_of(http, openalex_id="A1")
    assert first.copies == ["10.48550/arxiv.2401.1"]
    assert found[1] | {"item_id": None} == {
        "doi": "10.1000/new",
        "title": "Not yet",
        "year": None,
        "journal": None,
        "item_id": None,
    }
    assert asked == ["author.id:A123"]
    # Without an id, nothing is asked.
    assert ada.get(f"/api/authors/{ned}/works").json() == []
    assert len(asked) == 1


def test_ones_own_works(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    asked: list[str] = []
    client.app.state.http = openalex(ENTRIES, asked)  # ty: ignore[unresolved-attribute]
    assert ada.get("/api/me/works").json() == []
    ada.put("/api/auth/profile", {"orcid": ORCID})
    found = ada.get("/api/me/works").json()
    assert [w["doi"] for w in found] == ["10.1000/here", "10.1000/new"]
    assert asked == [f"author.orcid:https://orcid.org/{ORCID}"]


def test_openalex_down(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    ada.put("/api/auth/profile", {"orcid": ORCID})

    def down(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503)

    client.app.state.http = httpx2.Client(transport=httpx2.MockTransport(down))  # ty: ignore[unresolved-attribute]
    assert ada.get("/api/me/works").status_code == 502
    http = httpx2.Client(transport=httpx2.MockTransport(down))
    assert works.works_of(http) == []
