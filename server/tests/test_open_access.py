"""Downloading a damaged file again from an open-access source."""

from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from sqlalchemy import update
from sqlalchemy.orm import Session

from paperus.app import create_app
from paperus.config import Settings
from paperus.models import File, TextStatus
from tests.conftest import FakeDOIRegistry, FakeML
from tests.pdfs import make_pdf
from tests.people import Person

GOOD = make_pdf([["Floquet engineering of spin qubits"]])
BROKEN = b"%PDF-1.7\n1 0 obj << /Type /Catalog"  # cut off


class FakeSources:
    """arXiv and Unpaywall; ``arxiv`` is what arXiv answers."""

    def __init__(self) -> None:
        self.arxiv: bytes = GOOD
        self.asked: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.asked.append(str(request.url))
        if request.url.host == "arxiv.org":
            return httpx2.Response(200, content=self.arxiv)
        if request.url.host == "api.unpaywall.org":
            pdf = "https://oa.example.org/paper.pdf"
            return httpx2.Response(200, json={"best_oa_location": {"url_for_pdf": pdf}})
        if request.url.host == "oa.example.org":
            return httpx2.Response(200, content=GOOD)
        return httpx2.Response(404)


@pytest.fixture
def sources() -> FakeSources:
    return FakeSources()


@pytest.fixture
def site(
    settings: Settings,
    db: Session,
    doi_registry: FakeDOIRegistry,
    job_app: App,
    fake_ml: FakeML,
    sources: FakeSources,
) -> Iterator[TestClient]:
    def route(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "doi.org":
            return doi_registry(request)
        return sources(request)

    app = create_app(
        settings,
        http_client=httpx2.Client(transport=httpx2.MockTransport(route)),
        job_app=job_app,
        ml_client=fake_ml.client(),
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def broken_paper(ada: Person, db: Session, **identifier: str) -> dict[str, Any]:
    body: dict[str, Any] = {"metadata": {"title": "Floquet engineering"}}
    if identifier:
        [(scheme, value)] = identifier.items()
        body["identifiers"] = [{"scheme": scheme, "value": value}]
    item = ada.post("/api/items", json=body).json()
    file: dict[str, Any] = ada.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("2601.pdf", BROKEN, "application/pdf")},
    ).json()
    db.execute(update(File).values(text_status=TextStatus.FAILED, text_error="damaged"))
    db.commit()
    return file


def test_from_arxiv(site: TestClient, db: Session, sources: FakeSources) -> None:
    ada = Person(site, db, "ada")
    file = broken_paper(ada, db, arxiv="2601.01234")
    [listed] = ada.get("/api/files/unreadable").json()
    assert listed["can_download"] is True
    fresh = ada.post(f"/api/files/{file['id']}/download-again")
    assert fresh.status_code == 200, fresh.text
    assert (fresh.json()["source"], fresh.json()["text_status"]) == (
        "open_access",
        "pending",
    )
    assert "https://arxiv.org/pdf/2601.01234" in sources.asked
    assert ada.get(f"/api/files/{file['id']}/content").content == GOOD
    assert ada.get("/api/files/unreadable").json() == []


def test_a_web_page_is_not_taken(
    site: TestClient, db: Session, sources: FakeSources
) -> None:
    ada = Person(site, db, "ada")
    file = broken_paper(ada, db, arxiv="2601.01234")
    sources.arxiv = b"<html>Please log in</html>"
    refused = ada.post(f"/api/files/{file['id']}/download-again")
    assert refused.status_code == 409
    assert "not a PDF" in refused.json()["detail"]
    assert ada.get(f"/api/files/{file['id']}/content").content == BROKEN


def test_by_doi_through_unpaywall(
    site: TestClient, db: Session, sources: FakeSources
) -> None:
    root = Person(site, db, "root", admin=True)
    config = root.get("/api/admin/config").json()
    root.put("/api/admin/config", json={**config, "contact_email": "lab@example.org"})
    ada = Person(site, db, "ada")
    file = broken_paper(ada, db, doi="10.1103/physrevb.1.2")
    fresh = ada.post(f"/api/files/{file['id']}/download-again")
    assert fresh.status_code == 200, fresh.text
    assert any(
        "api.unpaywall.org/v2/10.1103/physrevb.1.2" in url for url in sources.asked
    )


def test_without_identifiers_nothing_to_fetch(site: TestClient, db: Session) -> None:
    ada = Person(site, db, "ada")
    file = broken_paper(ada, db)
    [listed] = ada.get("/api/files/unreadable").json()
    assert listed["can_download"] is False
    refused = ada.post(f"/api/files/{file['id']}/download-again")
    assert refused.status_code == 409
    assert "no open-access source" in refused.json()["detail"]
