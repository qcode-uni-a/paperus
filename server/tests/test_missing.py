"""Manage → Missing: papers without a file, and open-access copies for them
(their arXiv version found via OpenAlex)."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy.orm import Session

from paperus import missing
from paperus.app import create_app
from paperus.config import Settings
from paperus.identifiers import Scheme
from paperus.models import Identifier, Item, Version, VersionKind
from tests.conftest import FakeDOIRegistry, FakeML
from tests.pdfs import make_pdf
from tests.people import Person

PREPRINT = make_pdf([["Phonon-coupled hole-spin qubits, the preprint"]])
JOURNAL = make_pdf([["Phonon-coupled hole-spin qubits, as published"]])
PUBLISHED = "10.1088/2058-9565/ae0a7d"
ARXIV = "2504.12221"


class FakeWeb:
    """OpenAlex (``on_arxiv``: DOI → arXiv ID) and arXiv."""

    def __init__(self) -> None:
        self.on_arxiv: dict[str, str] = {}
        self.journal_open: set[str] = set()
        """DOIs whose journal version OpenAlex lists as open."""
        self.asked: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.asked.append(str(request.url))
        if request.url.host == "api.openalex.org":
            doi = request.url.path.removeprefix("/works/doi:")
            locations: list[dict[str, Any]] = [
                {"landing_page_url": "https://doi.org/x"}
            ]
            if doi in self.journal_open:
                locations[0] |= {
                    "is_oa": True,
                    "version": "publishedVersion",
                    "pdf_url": "https://journal.example.org/paper.pdf",
                }
            if doi in self.on_arxiv:
                abs_url = f"http://arxiv.org/abs/{self.on_arxiv[doi]}"
                locations.append({"landing_page_url": abs_url, "is_oa": True,
                                  "version": "submittedVersion"})  # fmt: skip
            return httpx2.Response(200, json={"locations": locations})
        if request.url.host == "arxiv.org":
            return httpx2.Response(200, content=PREPRINT)
        if request.url.host == "api.unpaywall.org":
            # The arXiv copy first: not the journal's, so left out.
            locations = [
                {
                    "url_for_pdf": f"https://arxiv.org/pdf/{ARXIV}",
                    "version": "submittedVersion",
                },
                {
                    "url_for_pdf": "https://journal.example.org/paper.pdf",
                    "version": "publishedVersion",
                },
            ]
            best = {
                "url_for_pdf": "https://journal.example.org/paper.pdf",
                "version": "publishedVersion",
            }
            return httpx2.Response(
                200, json={"oa_locations": locations, "best_oa_location": best}
            )
        if request.url.host == "journal.example.org":
            return httpx2.Response(200, content=JOURNAL)
        return httpx2.Response(404)


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


@pytest.fixture
def site(
    settings: Settings,
    db: Session,
    doi_registry: FakeDOIRegistry,
    job_app: App,
    fake_ml: FakeML,
    web: FakeWeb,
) -> Iterator[TestClient]:
    def route(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "doi.org":
            return doi_registry(request)
        return web(request)

    app = create_app(
        settings,
        http_client=httpx2.Client(transport=httpx2.MockTransport(route)),
        job_app=job_app,
        ml_client=fake_ml.client(),
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def published(registry: FakeDOIRegistry) -> None:
    registry.records[PUBLISHED] = {
        "type": "article-journal",
        "title": "Phonon-coupled hole-spin qubits in high-purity germanium",
        "DOI": PUBLISHED,
        "issued": {"date-parts": [[2025]]},
    }
    registry.records[f"10.48550/arxiv.{ARXIV}"] = {
        "type": "article",
        "title": "Phonon-coupled hole-spin qubits in germanium",
        "DOI": f"10.48550/arXiv.{ARXIV}",
        "issued": {"date-parts": [[2025]]},
    }


def listed(person: Person, **params: str) -> dict[str, Any]:
    response = person.get("/api/manage/missing", params=params)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def test_missing_lists_papers_without_files(
    site: TestClient, db: Session, doi_registry: FakeDOIRegistry
) -> None:
    published(doi_registry)
    ada = Person(site, db, "ada")
    paper = ada.post("/api/items", json={"doi": PUBLISHED}).json()
    page = ada.add("A web page")
    with_file = ada.add("Has its PDF")
    ada.post(
        f"/api/items/{with_file['id']}/files",
        files={"upload": ("p.pdf", PREPRINT, "application/pdf")},
    )
    found = listed(ada)
    assert [p["item"]["title"] for p in found["papers"]] == [
        "A web page",
        paper["title"],
    ]
    assert [p["open_access"] for p in found["papers"]] == [False, True]
    assert ada.get("/api/manage/counts").json()["missing"] == 2

    # No file needed: it leaves the list, and comes back.
    url = f"/api/items/{page['id']}/file-wanted"
    assert ada.put(url, {"wanted": False}).status_code == 204
    assert (listed(ada)["total"], listed(ada)["hidden"]) == (1, 1)
    assert listed(ada, hidden="true")["papers"][0]["item"]["id"] == page["id"]
    ada.put(url, {"wanted": True})
    assert listed(ada)["total"] == 2


def test_the_arxiv_version_brings_the_pdf(
    site: TestClient, db: Session, doi_registry: FakeDOIRegistry, web: FakeWeb
) -> None:
    published(doi_registry)
    web.on_arxiv[PUBLISHED] = ARXIV
    ada = Person(site, db, "ada")
    paper = ada.post("/api/items", json={"doi": PUBLISHED}).json()
    response = ada.post(f"/api/items/{paper['id']}/open-access")
    assert response.status_code == 200, response.text
    file = response.json()
    assert file["source"] == "open_access" and file["filename"] == f"arXiv {ARXIV}.pdf"

    detail = ada.get(f"/api/items/{paper['id']}").json()
    kinds = {v["kind"]: v for v in detail["versions"]}
    assert set(kinds) == {"published", "preprint"}
    # The PDF is the preprint's; the published version is still the one shown.
    assert [f["id"] for f in kinds["preprint"]["files"]] == [file["id"]]
    assert kinds["published"]["files"] == []
    assert detail["title"] == "Phonon-coupled hole-spin qubits in high-purity germanium"
    assert listed(ada)["total"] == 0


def test_no_copy_found(
    site: TestClient, db: Session, doi_registry: FakeDOIRegistry
) -> None:
    published(doi_registry)
    ada = Person(site, db, "ada")
    paper = ada.post("/api/items", json={"doi": PUBLISHED}).json()
    # Not on arXiv, and no contact email for Unpaywall.
    response = ada.post(f"/api/items/{paper['id']}/open-access")
    assert response.status_code == 409
    [entry] = listed(ada)["papers"]
    assert entry["tried_at"] is not None and entry["error"]
    # Others may see but not change a person's papers.
    eve = Person(site, db, "eve")
    assert eve.post(f"/api/items/{paper['id']}/open-access").status_code == 404


def test_try_all_and_the_background_sweep(
    site: TestClient, db: Session, doi_registry: FakeDOIRegistry, job_app: App
) -> None:
    published(doi_registry)
    ada = Person(site, db, "ada")
    on_arxiv = ada.post(
        "/api/items",
        json={
            "metadata": {"title": "Preprint"},
            "identifiers": [{"scheme": "arxiv", "value": ARXIV}],
        },
    ).json()
    ada.add("No identifiers")
    queued = ada.post("/api/manage/missing/open-access").json()
    assert queued == {"papers": 1}
    assert isinstance(job_app.connector, InMemoryConnector)
    jobs = [
        job
        for job in job_app.connector.jobs.values()
        if job["task_name"] == "paperus:fetch_open_access"
    ]
    assert [job["args"]["item_id"] for job in jobs] == [on_arxiv["id"]]

    # The sweep (with the setting on) takes papers with an identifier that
    # were never tried, once they are a little older.
    soon = datetime.now(UTC) + timedelta(minutes=5)
    waiting = missing.never_tried(db, added_before=soon, limit=10)
    assert [item_id for item_id, _ in waiting] == [uuid.UUID(on_arxiv["id"])]
    earlier = datetime.now(UTC) - timedelta(minutes=5)
    assert missing.never_tried(db, added_before=earlier, limit=10) == []


def test_only_the_preprint(
    site: TestClient, db: Session, doi_registry: FakeDOIRegistry, web: FakeWeb
) -> None:
    published(doi_registry)
    web.on_arxiv[PUBLISHED] = ARXIV
    root = Person(site, db, "root", admin=True)
    ada = Person(site, db, "ada")
    paper = ada.post("/api/items", json={"doi": PUBLISHED}).json()
    ada.post(f"/api/items/{paper['id']}/open-access")  # the arXiv version's PDF

    journal = listed(ada, section="journal")
    assert journal["counts"] == {"file": 0, "journal": 1}
    [entry] = journal["papers"]
    detail = ada.get(f"/api/items/{paper['id']}").json()
    published_id = next(v["id"] for v in detail["versions"] if v["kind"] == "published")
    assert entry["version_id"] == published_id and entry["open_access"] is True
    # OpenAlex knows no open journal copy, and Unpaywall needs an email.
    url = f"/api/items/{paper['id']}/open-access?section=journal"
    refused = ada.post(url)
    assert refused.status_code == 409 and "contact email" in refused.text

    config = root.get("/api/admin/config").json()
    root.put("/api/admin/config", {**config, "contact_email": "lab@example.org"})
    response = ada.post(url)
    assert response.status_code == 200, response.text
    assert response.json()["version_id"] == published_id
    assert listed(ada, section="journal")["total"] == 0
    assert ada.get("/api/manage/counts").json()["missing_journal"] == 0


def test_the_journals_open_copy_comes_first(
    site: TestClient, db: Session, doi_registry: FakeDOIRegistry, web: FakeWeb
) -> None:
    published(doi_registry)
    web.on_arxiv[PUBLISHED] = ARXIV
    web.journal_open.add(PUBLISHED)
    ada = Person(site, db, "ada")
    paper = ada.post("/api/items", json={"doi": PUBLISHED}).json()
    file = ada.post(f"/api/items/{paper['id']}/open-access").json()
    detail = ada.get(f"/api/items/{paper['id']}").json()
    kinds = {v["kind"]: v for v in detail["versions"]}
    # The published version has the journal's copy; complete, not missing.
    assert [f["id"] for f in kinds["published"]["files"]] == [file["id"]]
    assert kinds["preprint"]["files"] == []
    assert listed(ada)["counts"] == {"file": 0, "journal": 0}


def test_the_arxiv_version_unknown_at_doi_org(
    site: TestClient, db: Session, doi_registry: FakeDOIRegistry, web: FakeWeb
) -> None:
    published(doi_registry)
    del doi_registry.records[f"10.48550/arxiv.{ARXIV}"]
    web.on_arxiv[PUBLISHED] = ARXIV
    ada = Person(site, db, "ada")
    paper = ada.post("/api/items", json={"doi": PUBLISHED}).json()
    # OpenAlex knows its arXiv version, doi.org does not: no copy from there.
    assert ada.post(f"/api/items/{paper['id']}/open-access").status_code == 409
    detail = ada.get(f"/api/items/{paper['id']}").json()
    assert [v["kind"] for v in detail["versions"]] == ["published"]


def test_a_preprint_by_its_doi_through_unpaywall(
    site: TestClient, db: Session, doi_registry: FakeDOIRegistry
) -> None:
    doi = "10.21203/rs.3.rs-1/v1"
    doi_registry.records[doi] = {"type": "posted-content", "title": "A preprint"}
    root = Person(site, db, "root", admin=True)
    config = root.get("/api/admin/config").json()
    root.put("/api/admin/config", {**config, "contact_email": "lab@example.org"})
    ada = Person(site, db, "ada")
    paper = ada.post("/api/items", json={"doi": doi}).json()
    response = ada.post(f"/api/items/{paper['id']}/open-access")
    assert response.status_code == 200, response.text
    # Named by its DOI, without the characters file systems refuse.
    assert response.json()["filename"] == "10.21203_rs.3.rs-1_v1.pdf"


def test_a_journal_version_known_only_by_its_arxiv_doi() -> None:
    arxiv_doi = Identifier(scheme=Scheme.DOI, value=f"10.48550/arxiv.{ARXIV}")
    version = Version(kind=VersionKind.PUBLISHED, identifiers=[arxiv_doi])
    item = Item(title="Phonon-coupled", versions=[version])
    assert missing.journal_version(item) is version
    # No journal DOI to ask for the journal's copy with.
    assert missing.journal_doi(item) is None
