"""Search within one owner's papers, the reranker asked for by name (as the
evaluation does), and an ML service that cannot say where it runs."""

import uuid

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.access import Access
from paperus.api.search import run_search
from paperus.config import Settings
from paperus.embedding import embed_file
from paperus.models import User
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.conftest import FakeML
from tests.people import Person, group
from tests.test_meaning import MODEL


class NoDevice(FakeML):
    """Embeds and reranks, but does not answer where it runs."""

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/config":
            return httpx2.Response(503)
        return super().__call__(request)


@pytest.fixture
def fake_ml() -> FakeML:
    return NoDevice()


def add(
    person: Person,
    db: Session,
    blobs: BlobStore,
    ml: FakeML,
    title: str,
    library: str | None = None,
) -> None:
    item = person.add(title, library)
    file = person.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("notes.md", f"{title}, drizzle".encode(), "text/markdown")},
    ).json()
    process_file(db, blobs, uuid.UUID(file["id"]))
    embed_file(db, ml.client(), MODEL, uuid.UUID(file["id"]))


def titles(person: Person, **params: str) -> list[str]:
    response = person.get("/api/search", params={"q": "rain", **params})
    assert response.status_code == 200, response.text
    # The papers found (each may be found by its title and by its text).
    return sorted({p["item_title"] for p in response.json()})


def test_one_owners_papers(
    client: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    chair = group(root, "Chair", ada)
    add(ada, db, blobs, fake_ml, "Rain at home")
    add(ada, db, blobs, fake_ml, "Rain at the chair", chair["library_id"])
    # Auto: no reranking when the service does not say it has a GPU.
    assert titles(ada) == ["Rain at home", "Rain at the chair"]
    assert fake_ml.reranked == []
    assert titles(ada, library=chair["library_id"]) == ["Rain at the chair"]
    # Another owner's: nothing, as if it were empty.
    assert titles(ada, library=root.libraries()["Me"]["id"]) == []


def test_the_reranker_asked_for(
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    fake_ml: FakeML,
    settings: Settings,
) -> None:
    ada = Person(client, db, "ada")
    add(ada, db, blobs, fake_ml, "Rain gauges")
    user = db.get(User, uuid.UUID(ada.id))
    assert user is not None
    access = Access.of(db, user)
    used, found = run_search(
        db, access, fake_ml.client(), settings, "rain", rerank=True
    )
    assert used == "hybrid" and all(p.reranked for p in found)
    assert len(fake_ml.reranked) == 1
    _, found = run_search(db, access, fake_ml.client(), settings, "rain", rerank=False)
    assert found and not any(p.reranked for p in found)
    assert len(fake_ml.reranked) == 1
