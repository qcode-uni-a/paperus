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

from paperus.embedding import (
    embed_file,
    embed_note,
    files_missing_embeddings,
    notes_missing_embeddings,
)
from paperus.jobs import queue_embedding
from paperus.ml import MLClient, MLLoading, MLRejected, MLUnavailable
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


def test_another_model_file_is_embedded_again(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    """The ML service on a GPU runs another file of the model (fp16): its
    vectors are not mixed with the stored ones, the library is embedded
    again, as after a change of model."""
    file_id = uuid.UUID(prepare(logged_in, db, blobs, fake_ml))
    fake_ml.variant = "fp16"
    ml = fake_ml.client()
    assert ml.vectors_name(MODEL) == f"{MODEL}@fp16"
    assert files_missing_embeddings(db, f"{MODEL}@fp16") == [file_id]
    # Meanwhile search by meaning finds nothing rather than comparing with
    # vectors of the other file.
    assert search(logged_in, "missing", mode="meaning")[0] == []
    assert embed_file(db, ml, MODEL, file_id) == 1
    assert search(logged_in, "missing", mode="meaning")[0] != []
    assert set(db.scalars(select(Embedding.model))) == {MODEL, f"{MODEL}@fp16"}


def test_ml_client_falls_back_and_sends_token(fake_ml: FakeML) -> None:
    seen: list[httpx2.Request] = []

    def route(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.host == "gpu":
            return httpx2.Response(500)
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


def test_ml_client_loading_and_rejected(fake_ml: FakeML) -> None:
    """A model still loading is not a broken service; an unknown model is
    not worth trying elsewhere or again."""

    def loading(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, json={"detail": "model 'bge-m3' is loading"})

    client = MLClient(
        ["http://ml"], http=httpx2.Client(transport=httpx2.MockTransport(loading))
    )
    with pytest.raises(MLLoading, match="loading"):
        client.embed(["rain"], model=MODEL, kind="query")
    assert client._failed_at == {}
    with pytest.raises(MLRejected, match="unknown model"):
        fake_ml.client().embed(["rain"], model="gpt-9", kind="query")


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


def test_filter_by_type(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    prepare(logged_in, db, blobs, fake_ml)  # type "document"
    assert len(search(logged_in, "interpolation", type="document")[0]) == 1
    assert search(logged_in, "interpolation", type="book")[0] == []
    response = logged_in.get(
        "/api/search",
        params=[("q", "interpolation"), ("type", "book"), ("type", "document")],
    )
    assert len(response.json()) == 1


def test_references_found_by_words_not_by_meaning(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    content = (
        b"Rain gauges were checked weekly.\n\nReferences\n\n"
        b"[1] Huber, Missing data in rain records, 2024."
    )
    file_id = uuid.UUID(add_file(logged_in, "Notes", content)["id"])
    process_file(db, blobs, file_id)
    # Only the body is embedded.
    assert embed_file(db, fake_ml.client(), MODEL, file_id) == 1
    assert files_missing_embeddings(db, MODEL) == []

    [hit] = search(logged_in, "Huber", mode="keyword")[0]
    assert hit["in_references"] is True
    hits, _ = search(logged_in, "missing", mode="meaning")
    assert all(not h["in_references"] for h in hits)


def test_reread_all_marks_existing_files(
    admin: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML, job_app: App
) -> None:
    content = b"Body.\n\nReferences\n\n[1] Huber, 2024."
    file_id = uuid.UUID(add_file(admin, "Notes", content)["id"])
    process_file(db, blobs, file_id)
    response = admin.post("/api/admin/jobs/text-all")
    assert response.json() == {"queued": "text-all", "files": 1}
    assert admin.get(f"/api/items/{admin.get('/api/items').json()[0]['id']}").json()[
        "processing"
    ]
    process_file(db, blobs, file_id)
    hits, _ = search(admin, "Huber", mode="keyword")
    assert hits[0]["in_references"] is True


def test_notes_are_found_by_meaning(
    logged_in: TestClient, db: Session, fake_ml: FakeML, job_app: App
) -> None:
    note = logged_in.post(
        "/api/notes", json={"text": "# Station log\n\nGaps in the record."}
    ).json()
    # Saving queues the vectors; until then, words only.
    assert isinstance(job_app.connector, InMemoryConnector)
    jobs = [j["task_name"] for j in job_app.connector.jobs.values()]
    assert "paperus:embed_note" in jobs
    assert notes_missing_embeddings(db, MODEL) == [uuid.UUID(note["id"])]
    assert search(logged_in, "missing", mode="meaning")[0] == []

    assert embed_note(db, fake_ml.client(), MODEL, uuid.UUID(note["id"])) == 1
    assert notes_missing_embeddings(db, MODEL) == []
    [hit], _ = search(logged_in, "missing", mode="meaning")
    assert (hit["kind"], hit["note_id"], hit["item_id"]) == ("note", note["id"], None)
    assert hit["item_title"] == "Station log"
    # Types filter papers; notes only when asked for.
    assert search(logged_in, "gaps", type="article-journal")[0] == []
    assert len(search(logged_in, "gaps", type="note")[0]) == 1
    # Trashed notes are not found.
    logged_in.delete(f"/api/notes/{note['id']}")
    assert search(logged_in, "gaps")[0] == []


def test_similar_papers(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    def paper(title: str, text: bytes) -> str:
        item = logged_in.post("/api/items", json={"metadata": {"title": title}})
        item_id: str = item.json()["id"]
        file = logged_in.post(
            f"/api/items/{item_id}/files",
            files={"upload": ("notes.md", text, "text/markdown")},
        ).json()
        process_file(db, blobs, uuid.UUID(file["id"]))
        embed_file(db, fake_ml.client(), MODEL, uuid.UUID(file["id"]))
        return item_id

    rain = paper("Rain", b"Rain gauges measure rain every day in the Alps.")
    rainfall = paper("Rainfall", b"Rainfall gauges measure rainfall daily in Bavaria.")
    paper("Qubits", b"Spin qubits in silicon quantum dots.")
    logged_in.post("/api/items", json={"metadata": {"title": "No text yet"}})

    found = logged_in.get(f"/api/items/{rain}/similar").json()
    assert [f["title"] for f in found] == ["Rainfall", "Qubits"]
    assert found[0]["similarity"] > found[1]["similarity"]
    # Archived papers are left out.
    logged_in.put(f"/api/items/{rainfall}/archive")
    found = logged_in.get(f"/api/items/{rain}/similar").json()
    assert [f["title"] for f in found] == ["Qubits"]
