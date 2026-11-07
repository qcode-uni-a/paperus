"""Preprints get their published versions by themselves (arXiv, OpenAlex)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus import published
from paperus.models import Item, Version
from tests.conftest import FakeDOIRegistry
from tests.people import Person

NUMPY = "10.1038/s41586-020-2649-2"


def atom(entries: dict[str, str | None]) -> str:
    """arXiv's answer: an entry per paper, with the DOI its authors gave."""
    body = "".join(
        f"<entry><id>http://arxiv.org/abs/{paper}v2</id>"
        + (f"<arxiv:doi>{doi}</arxiv:doi>" if doi else "")
        + "</entry>"
        for paper, doi in entries.items()
    )
    return f"<feed>{body}</feed>"


class FakeSources:
    def __init__(self, registry: FakeDOIRegistry) -> None:
        self.registry = registry
        self.arxiv: dict[str, str | None] = {}
        self.openalex: dict[str, str] = {}
        self.asked: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.asked.append(request.url.host)
        if request.url.host == "doi.org":
            return self.registry(request)
        if request.url.host == "export.arxiv.org":
            ids = request.url.params["id_list"].split(",")
            return httpx2.Response(200, text=atom({i: self.arxiv.get(i) for i in ids}))
        if request.url.host == "api.openalex.org":
            paper = request.url.path.rsplit("arxiv.", 1)[-1]
            if paper not in self.openalex:
                return httpx2.Response(404)
            return httpx2.Response(
                200, json={"doi": f"https://doi.org/{self.openalex[paper]}"}
            )
        return httpx2.Response(404)


def preprint(
    ada: Person, registry: FakeDOIRegistry, paper: str, title: str
) -> dict[str, Any]:
    registry.records[f"10.48550/arxiv.{paper}"] = {"type": "article", "title": title}
    item: dict[str, Any] = ada.post(
        "/api/items", json={"doi": f"10.48550/arXiv.{paper}"}
    ).json()
    return item


def test_published_versions_are_found(
    client: TestClient, db: Session, doi_registry: FakeDOIRegistry
) -> None:
    ada = Person(client, db, "ada")
    numpy = preprint(ada, doi_registry, "2006.10256", "Array programming with NumPy")
    other = preprint(ada, doi_registry, "2401.00001", "Floquet engineering of qubits")
    alone = preprint(ada, doi_registry, "2401.00002", "Not published anywhere")
    taken = preprint(ada, doi_registry, "2401.00003", "Already in the library")
    doi_registry.records[NUMPY] = {
        "type": "journal-article",
        "title": "Array programming with NumPy",
        "container-title": "Nature",
    }
    # OpenAlex links a different paper: its title does not match.
    doi_registry.records["10.1103/wrong"] = {
        "type": "journal-article",
        "title": "Superconductivity in twisted bilayers",
    }
    doi_registry.records["10.1103/known"] = {
        "type": "journal-article",
        "title": "Already in the library",
    }
    ada.post("/api/items", json={"doi": "10.1103/known"})

    sources = FakeSources(doi_registry)
    sources.arxiv = {"2006.10256": NUMPY, "2401.00003": "10.1103/known"}
    sources.openalex = {"2401.00001": "10.1103/wrong"}
    http = httpx2.Client(transport=httpx2.MockTransport(sources))

    items = published.waiting(db, 10)
    assert {str(i.id) for i in items} == {
        numpy["id"],
        other["id"],
        alone["id"],
        taken["id"],
    }
    upgraded = published.check(db, http, items, contact_email=None, pause=0)
    assert [str(i.id) for i in upgraded] == [numpy["id"]]
    # One request to arXiv for all four.
    assert sources.asked.count("export.arxiv.org") == 1

    detail = ada.get(f"/api/items/{numpy['id']}").json()
    assert {v["kind"] for v in detail["versions"]} == {"preprint", "published"}
    assert detail["title"] == "Array programming with NumPy"
    assert detail["container_title"] == "Nature"
    for paper in (other, alone, taken):
        kinds = {
            v["kind"] for v in ada.get(f"/api/items/{paper['id']}").json()["versions"]
        }
        assert kinds == {"preprint"}

    # Checked: not again for a month; the found one never again.
    assert published.waiting(db, 10) == []
    later = datetime.now(UTC) + timedelta(days=31)
    again = {str(i.id) for i in published.waiting(db, 10, now=later)}
    assert again == {other["id"], alone["id"], taken["id"]}
    db.expire_all()
    found = db.get(Item, numpy["id"])
    assert found is not None and found.published_checked_at is not None


def test_in_batches_with_a_pause(
    client: TestClient,
    db: Session,
    doi_registry: FakeDOIRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ada = Person(client, db, "ada")
    preprint(ada, doi_registry, "2401.00001", "Floquet engineering of qubits")
    preprint(ada, doi_registry, "2401.00002", "Not published anywhere")
    sources = FakeSources(doi_registry)
    http = httpx2.Client(transport=httpx2.MockTransport(sources))
    monkeypatch.setattr(published, "ARXIV_BATCH", 1)
    paused: list[float] = []
    monkeypatch.setattr(published.time, "sleep", paused.append)
    assert (
        published.check(db, http, published.waiting(db, 10), contact_email=None) == []
    )
    # One request to arXiv per batch, a pause between them.
    assert sources.asked.count("export.arxiv.org") == 2
    assert paused == [published.ARXIV_PAUSE]


def down(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("unreachable", request=request)


def answering(response: httpx2.Response) -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(lambda request: response))


def test_sources_that_do_not_answer(db: Session) -> None:
    unreachable = httpx2.Client(transport=httpx2.MockTransport(down))
    assert published.arxiv_dois(unreachable, []) == {}
    assert published.arxiv_dois(unreachable, ["2401.00001"]) == {}
    assert published.arxiv_dois(answering(httpx2.Response(503)), ["2401.00001"]) == {}
    assert published.openalex_doi(unreachable, "2401.00001", None) is None
    # OpenAlex's work for a preprint may be the preprint itself.
    asked: list[httpx2.Request] = []

    def openalex(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        return httpx2.Response(200, json={"doi": "https://doi.org/10.48550/arxiv.1"})

    http = httpx2.Client(transport=httpx2.MockTransport(openalex))
    assert published.openalex_doi(http, "2401.00001", "lab@example.org") is None
    assert asked[0].url.params["mailto"] == "lab@example.org"

    # Neither an arXiv ID to look for, nor a DOI to take.
    item = Item(title="Floquet", versions=[Version()])
    assert published.arxiv_id(item) is None
    assert published.add_published(db, unreachable, item, "no DOI", "arXiv") is None
