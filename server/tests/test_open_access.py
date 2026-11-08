"""Downloading a damaged file again from an open-access source."""

from collections.abc import Callable, Iterator
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from sqlalchemy import update
from sqlalchemy.orm import Session

from paperus import open_access
from paperus.app import create_app
from paperus.config import Settings
from paperus.identifiers import Scheme
from paperus.models import File, Identifier, Item, TextStatus, Version
from paperus.storage import BlobStore
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


# The sources one by one, as they fail.

Handler = Callable[[httpx2.Request], httpx2.Response]


def web(handler: Handler) -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(handler))


def down(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("unreachable", request=request)


def paper(scheme: Scheme, value: str) -> Item:
    """A paper with one identifier (not stored)."""
    identifier = Identifier(scheme=scheme, value=value)
    return Item(title="Floquet", versions=[Version(identifiers=[identifier])])


def test_openalex_on_arxiv_or_not() -> None:
    doi = "10.1103/physrevb.1.2"
    assert open_access.arxiv_id_for(web(down), doi, None) is None
    unknown = web(lambda request: httpx2.Response(503))
    assert open_access.arxiv_id_for(unknown, doi, None) is None
    asked: list[httpx2.Request] = []

    def openalex(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        locations = [
            "not a location",
            {"landing_page_url": "https://journals.aps.org/x"},
            {"pdf_url": "https://arxiv.org/pdf/2401.00001v2.pdf"},
        ]
        return httpx2.Response(200, json={"locations": locations})

    assert open_access.arxiv_id_for(web(openalex), doi, "lab@example.org") == (
        "2401.00001"
    )
    assert asked[0].url.params["mailto"] == "lab@example.org"


def test_unpaywall_without_a_copy(blobs: BlobStore) -> None:
    item = paper(Scheme.DOI, "10.1103/physrevb.1.2")
    for answer in (
        httpx2.Response(500),
        httpx2.Response(200, json={"best_oa_location": None}),
        httpx2.Response(200, json={"best_oa_location": {"url_for_pdf": "http://x"}}),
    ):
        with pytest.raises(open_access.NoSource, match="no open-access PDF"):
            open_access.fetch(
                web(lambda request, answer=answer: answer),
                blobs,
                item,
                contact_email="lab@example.org",
                max_bytes=10**6,
            )
    # Without a contact email Unpaywall is not asked (OpenAlex is).
    asked: list[str] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        asked.append(str(request.url.host))
        return httpx2.Response(404)

    with pytest.raises(open_access.NoSource, match="no open-access PDF"):
        open_access.fetch(web(answer), blobs, item, contact_email=None, max_bytes=10)
    assert asked == ["api.openalex.org"]


def test_every_open_copy_is_tried(blobs: BlobStore) -> None:
    """arXiv, then repositories, the publisher last; one refusing copy (as
    publishers refuse servers) does not end the search."""
    tried: list[str] = []
    openalex = [
        {"is_oa": True, "pdf_url": "https://journal.example/x.pdf"},
        {
            "is_oa": True,
            "pdf_url": "https://repo.example/x.pdf",
            "source": {"type": "repository"},
        },
        {"is_oa": False, "pdf_url": "https://closed.example/x.pdf"},
        {"is_oa": True, "pdf_url": "http://plain.example/x.pdf"},
        {"is_oa": True, "source": None},
    ]
    unpaywall = {
        "best_oa_location": {
            "url_for_pdf": "https://journal.example/x.pdf",
            "host_type": "publisher",
        },
        "oa_locations": [
            {"url_for_pdf": "https://csic.example/x.pdf", "host_type": "repository"},
            "not a location",
        ],
    }

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.openalex.org":
            return httpx2.Response(200, json={"locations": openalex})
        if request.url.host == "api.unpaywall.org":
            return httpx2.Response(200, json=unpaywall)
        tried.append(str(request.url))
        if request.url.host == "csic.example":
            return httpx2.Response(200, content=GOOD)
        return httpx2.Response(403)

    doi = "10.1103/physrevb.1.2"
    assert open_access.open_copies(web(answer), doi, "a@b.org") == [
        "https://repo.example/x.pdf",
        "https://csic.example/x.pdf",
        "https://journal.example/x.pdf",
    ]
    _, url = open_access.fetch(
        web(answer),
        blobs,
        paper(Scheme.DOI, doi),
        contact_email="a@b.org",
        max_bytes=10**6,
    )
    assert url == "https://csic.example/x.pdf"
    assert tried == ["https://repo.example/x.pdf", "https://csic.example/x.pdf"]

    # Unpaywall unreachable or failing: OpenAlex's copies still count.
    def no_unpaywall(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.unpaywall.org":
            raise httpx2.ConnectError("down", request=request)
        return answer(request)

    def unpaywall_fails(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.unpaywall.org":
            return httpx2.Response(500)
        return answer(request)

    for handler in (no_unpaywall, unpaywall_fails):
        assert open_access.open_copies(web(handler), doi, "a@b.org") == [
            "https://repo.example/x.pdf",
            "https://journal.example/x.pdf",
        ]


def test_too_large_is_not_stored(blobs: BlobStore) -> None:
    arxiv = web(lambda request: httpx2.Response(200, content=GOOD))
    with pytest.raises(open_access.NoSource, match=r"arxiv\.org/pdf/2401\.00001"):
        open_access.fetch(
            arxiv,
            blobs,
            paper(Scheme.ARXIV, "2401.00001"),
            contact_email=None,
            max_bytes=len(GOOD) - 1,
        )
    stored, url = open_access.fetch(
        arxiv,
        blobs,
        paper(Scheme.ARXIV, "2401.00001"),
        contact_email=None,
        max_bytes=len(GOOD),
    )
    assert url == "https://arxiv.org/pdf/2401.00001" and stored.size == len(GOOD)


def test_the_journals_copy_refused(blobs: BlobStore) -> None:
    doi = "10.1103/physrevb.1.2"

    def sources(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.openalex.org":
            open_copy = {"is_oa": True, "version": "publishedVersion"}
            locations = [
                {**open_copy, "pdf_url": "http://insecure.example.org/paper.pdf"},
                {**open_copy, "pdf_url": "https://journal.example.org/login"},
                {"is_oa": True, "version": "submittedVersion", "pdf_url": "x"},
            ]
            return httpx2.Response(200, json={"locations": locations})
        if request.url.host == "journal.example.org":
            return httpx2.Response(200, text="<html>Please log in</html>")
        return httpx2.Response(404)

    # Only what was tried, and why (never the insecure address).
    with pytest.raises(open_access.NoSource) as refused:
        open_access.fetch_journal_copy(
            web(sources), blobs, doi, contact_email=None, max_bytes=10**6
        )
    assert str(refused.value) == (
        "https://journal.example.org/login: not a PDF (probably a web page)"
    )
    nothing = web(lambda request: httpx2.Response(404))
    with pytest.raises(open_access.NoSource, match="with the contact email set"):
        open_access.fetch_journal_copy(
            nothing, blobs, doi, contact_email=None, max_bytes=10
        )
    with pytest.raises(open_access.NoSource, match=r"^no open copy of the journal"):
        open_access.fetch_journal_copy(
            nothing, blobs, doi, contact_email="lab@example.org", max_bytes=10
        )
