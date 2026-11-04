"""Embeddings, the ML client, and search by meaning (with a fake ML service)."""

import uuid
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paperus.embedding import embed_file, files_missing_embeddings
from paperus.jobs import queue_embedding
from paperus.ml import MLClient, MLUnavailable
from paperus.models import Embedding
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.conftest import FakeML

MODEL = "bge-m3"
NOTES = (
    b"Gaps shorter than five days were filled by linear interpolation.\n\n"
    b"Rain gauges were checked weekly."
)


def add_file(client: TestClient, title: str, content: bytes = NOTES) -> dict[str, Any]:
    item = client.post("/api/items", json={"metadata": {"title": title}}).json()
    file: dict[str, Any] = client.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("notes.md", content, "text/markdown")},
    ).json()
    return file


def prepare(
    client: TestClient, db: Session, blobs: BlobStore, ml: FakeML, title: str = "Notes"
) -> str:
    file = add_file(client, title)
    file_id = uuid.UUID(file["id"])
    process_file(db, blobs, file_id)
    embed_file(db, ml.client(), MODEL, file_id)
    return file["id"]


def search(
    client: TestClient, q: str, **params: str
) -> tuple[list[dict[str, Any]], str]:
    response = client.get("/api/search", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json(), response.headers["X-Search-Mode"]


def test_embed_file_once_per_chunk(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    file = add_file(logged_in, "A")
    file_id = uuid.UUID(file["id"])
    process_file(db, blobs, file_id)
    assert files_missing_embeddings(db, MODEL) == [file_id]
    assert embed_file(db, fake_ml.client(), MODEL, file_id) == 1
    assert embed_file(db, fake_ml.client(), MODEL, file_id) == 0
    assert files_missing_embeddings(db, MODEL) == []
    assert fake_ml.requests[0]["kind"] == "passage"

    # The same text in another file reuses the vector.
    other = uuid.UUID(add_file(logged_in, "B")["id"])
    process_file(db, blobs, other)
    assert embed_file(db, fake_ml.client(), MODEL, other) == 0

    # Another model: everything is missing again (re-embedding after a change).
    assert set(files_missing_embeddings(db, "other-model")) == {file_id, other}
    count = db.scalar(select(func.count()).select_from(Embedding))
    assert count == 1


def test_hybrid_search_finds_by_meaning(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    prepare(logged_in, db, blobs, fake_ml)
    # No word in common with the passage, only its meaning ("gaps").
    assert search(logged_in, "missing", mode="keyword")[0] == []
    hits, mode = search(logged_in, "missing")
    assert mode == "hybrid"
    assert hits[0]["matched"] == ["meaning"]
    assert "Gaps shorter" in hits[0]["snippet"]

    hits, _ = search(logged_in, "interpolation")
    assert hits[0]["matched"] == ["keyword", "meaning"]
    assert "<mark>interpolation</mark>" in hits[0]["snippet"]
    assert fake_ml.requests[-1]["kind"] == "query"


def test_meaning_only(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    prepare(logged_in, db, blobs, fake_ml)
    hits, mode = search(logged_in, "absent", mode="meaning")
    assert mode == "meaning"
    assert [h["matched"] for h in hits] == [["meaning"]]


def test_keyword_mode_needs_no_ml(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    prepare(logged_in, db, blobs, fake_ml)
    calls = len(fake_ml.requests)
    hits, mode = search(logged_in, "interpolation", mode="keyword")
    assert mode == "keyword"
    assert hits[0]["matched"] == ["keyword"]
    assert len(fake_ml.requests) == calls


def test_falls_back_to_keywords_without_ml(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    prepare(logged_in, db, blobs, fake_ml)
    fake_ml.down = True
    hits, mode = search(logged_in, "interpolation")
    assert mode == "keyword"
    assert len(hits) == 1
    assert search(logged_in, "missing", mode="meaning")[0] == []


def test_trashed_files_are_not_found_by_meaning(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    file_id = prepare(logged_in, db, blobs, fake_ml)
    logged_in.delete(f"/api/files/{file_id}")
    assert search(logged_in, "missing")[0] == []


def test_ml_client_falls_back_and_sends_token(fake_ml: FakeML) -> None:
    seen: list[httpx2.Request] = []

    def route(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.host == "gpu":
            return httpx2.Response(503)
        return fake_ml(request)

    http = httpx2.Client(transport=httpx2.MockTransport(route))
    client = MLClient(["http://gpu", "http://local/"], token="t0ken", http=http)
    assert (
        len(client.embed(["rain"], model=MODEL, kind="query")[0]) == FakeML.DIMENSIONS
    )
    assert [r.url.host for r in seen] == ["gpu", "local"]
    assert seen[-1].headers["Authorization"] == "Bearer t0ken"
    # The failing address is tried last for a while.
    client.embed(["rain"], model=MODEL, kind="query")
    assert [r.url.host for r in seen[2:]] == ["local"]


def test_ml_client_raises_when_all_fail() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    client = MLClient(
        ["http://a", "http://b"],
        http=httpx2.Client(transport=httpx2.MockTransport(down)),
    )
    with pytest.raises(MLUnavailable, match=r"http://a.*http://b"):
        client.embed(["x"], model=MODEL, kind="passage")


def test_queue_embedding_once(job_app: App) -> None:
    file_id = uuid.uuid4()
    with job_app.open():
        queue_embedding(job_app, file_id)
        queue_embedding(job_app, file_id)
    assert isinstance(job_app.connector, InMemoryConnector)
    jobs = list(job_app.connector.jobs.values())
    assert [(j["task_name"], j["args"]) for j in jobs] == [
        ("paperus:embed_file", {"file_id": str(file_id)})
    ]
