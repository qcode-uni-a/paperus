import uuid

import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from paperus import system
from paperus.config import Settings
from paperus.embedding import embed_file
from paperus.jobs import send_ml_config
from paperus.models import File, TextStatus
from paperus.processing import process_file
from paperus.storage import BlobStore
from paperus.system import load_config
from tests.conftest import FakeML
from tests.pdfs import make_pdf
from tests.people import Person


def queued(job_app: App) -> list[str]:
    assert isinstance(job_app.connector, InMemoryConnector)
    return [j["task_name"] for j in job_app.connector.jobs.values()]


def test_admins_only(logged_in: TestClient) -> None:
    for path in ["/api/admin/config", "/api/admin/ml", "/api/admin/stats"]:
        assert logged_in.get(path).status_code == 403


def test_change_embedding_model(
    admin: TestClient, db: Session, settings: Settings, job_app: App, fake_ml: FakeML
) -> None:
    config = admin.get("/api/admin/config").json()
    assert (config["embedding_model"], config["ml_threads"]) == ("bge-m3", None)
    response = admin.put(
        "/api/admin/config",
        json={**config, "embedding_model": "multilingual-e5-small", "ml_threads": 6},
    )
    assert response.status_code == 200
    assert load_config(db, settings).embedding_model == "multilingual-e5-small"
    # The administrators are told when that is done (test_worker).
    assert (system.reembedding(db) or {}).get("model") == "multilingual-e5-small"
    # The library is re-embedded in the background, and the ML service gets
    # the new settings (first in the worker's queue).
    assert queued(job_app) == [
        "paperus:queue_missing_embeddings",
        "paperus:configure_ml",
    ]
    send_ml_config(db, settings, fake_ml.client())
    assert fake_ml.config == {"threads": 6, "keep": ["multilingual-e5-small"]}
    service = admin.get("/api/admin/ml").json()["service"]
    assert (service["threads"], service["cores"]) == (6, 8)
    assert service["url"] == "http://ml"
    assert (
        admin.put(
            "/api/admin/config", json={"embedding_model": "bge-m3", "ml_threads": -1}
        ).status_code
        == 422
    )

    unknown = admin.put("/api/admin/config", json={"embedding_model": "gpt-9"})
    assert unknown.status_code == 422


def test_model_change_needs_ml(admin: TestClient, fake_ml: FakeML) -> None:
    fake_ml.down = True
    response = admin.put(
        "/api/admin/config", json={"embedding_model": "multilingual-e5-small"}
    )
    assert response.status_code == 503
    # Saving without a change works without the ML service.
    assert (
        admin.put("/api/admin/config", json={"embedding_model": "bge-m3"}).status_code
        == 200
    )


def test_ml_status(admin: TestClient, fake_ml: FakeML) -> None:
    status = admin.get("/api/admin/ml").json()
    assert status["services"] == [{"url": "http://ml", "ok": True, "error": None}]
    assert [m["name"] for m in status["models"]] == (
        FakeML.MODELS + FakeML.RERANKERS + FakeML.OCR_MODELS
    )
    fake_ml.down = True
    status = admin.get("/api/admin/ml").json()
    assert status["services"][0]["ok"] is False
    assert status["models"] == []


def test_measure_speed(admin: TestClient, fake_ml: FakeML) -> None:
    speed = admin.post("/api/admin/ml/models/bge-m3/speed").json()
    assert (speed["model"], speed["passages_per_second"]) == ("bge-m3", 8.0)
    assert admin.post("/api/admin/ml/models/nope/speed").status_code == 404
    fake_ml.down = True
    assert admin.post("/api/admin/ml/models/bge-m3/speed").status_code == 503


def test_delete_cached_model(admin: TestClient, fake_ml: FakeML) -> None:
    assert admin.delete("/api/admin/ml/models/bge-m3").status_code == 409
    assert admin.delete("/api/admin/ml/models/multilingual-e5-small").status_code == 204
    assert fake_ml.deleted == ["multilingual-e5-small"]


def test_stats_and_progress(
    admin: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    item = admin.post("/api/items", json={"metadata": {"title": "Notes"}}).json()
    file = admin.post(
        f"/api/items/{item['id']}/files",
        files={
            "upload": ("n.md", b"Rain gauges were checked weekly.", "text/markdown")
        },
    ).json()
    stats = admin.get("/api/admin/stats").json()
    assert stats["items"] == 1
    assert stats["files_pending"] == 1
    assert stats["embedding_model"] == "bge-m3"

    process_file(db, blobs, uuid.UUID(file["id"]))
    stats = admin.get("/api/admin/stats").json()
    assert (stats["chunks"], stats["embedded"], stats["files_pending"]) == (1, 0, 0)
    embed_file(db, fake_ml.client(), "bge-m3", uuid.UUID(file["id"]))
    assert admin.get("/api/admin/stats").json()["embedded"] == 1

    # PDFs: laid out (and their passages cut by them) when read.
    paper = admin.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("p.pdf", make_pdf([["Rain gauges."]]), "application/pdf")},
    ).json()
    stats = admin.get("/api/admin/stats").json()
    assert (stats["pdfs_laid_out"], stats["pdfs"]) == (0, 1)
    process_file(db, blobs, uuid.UUID(paper["id"]))
    stats = admin.get("/api/admin/stats").json()
    assert (stats["pdfs_laid_out"], stats["pdfs"]) == (1, 1)


def test_run_jobs(admin: TestClient, job_app: App) -> None:
    assert admin.post("/api/admin/jobs/embeddings").status_code == 202
    assert admin.post("/api/admin/jobs/text").status_code == 202
    assert admin.post("/api/admin/jobs/nope").status_code == 404
    assert sorted(queued(job_app)) == [
        "paperus:queue_missing_embeddings",
        "paperus:queue_pending_files",
    ]


def test_read_failed_files_again(admin: TestClient, db: Session, job_app: App) -> None:
    item = admin.post("/api/items", json={"metadata": {"title": "Broken"}}).json()
    admin.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("b.pdf", b"%PDF-1.7 broken", "application/pdf")},
    )
    db.execute(update(File).values(text_status=TextStatus.FAILED, text_error="bad"))
    db.commit()
    assert admin.get("/api/admin/stats").json()["files_failed"] == 1
    started = admin.post("/api/admin/jobs/text-failed").json()
    assert started == {"queued": "text-failed", "files": 1}
    db.expire_all()
    assert db.scalar(select(File.text_status)) == TextStatus.PENDING
    assert admin.get("/api/admin/stats").json()["files_failed"] == 0


def test_date_format_for_everyone(client: TestClient, db: Session) -> None:
    """The administrator's choice of date format reaches every person with
    their account (login, /me, a new profile picture)."""
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    assert ada.get("/api/auth/me").json()["date_format"] == "browser"
    config = root.get("/api/admin/config").json()
    assert config["date_format"] == "browser"
    refused = root.put("/api/admin/config", json={**config, "date_format": "mars"})
    assert refused.status_code == 422
    saved = root.put("/api/admin/config", json={**config, "date_format": "europe"})
    assert saved.status_code == 200
    assert root.get("/api/admin/config").json()["date_format"] == "europe"
    assert ada.get("/api/auth/me").json()["date_format"] == "europe"
    login = client.post(
        "/api/auth/login", json={"username": "ada", "password": "secret"}
    )
    assert login.json()["user"]["date_format"] == "europe"
    removed = ada.delete("/api/me/avatar")
    assert removed.json()["date_format"] == "europe"


def test_multimodal_search_switched(
    admin: TestClient, db: Session, settings: Settings, job_app: App, fake_ml: FakeML
) -> None:
    """On: models that take images, the text ones kept; off: back to them.
    Recommended with a GPU of enough memory; models of the other kind refused."""
    state = admin.get("/api/admin/multimodal").json()
    assert state == {
        "on": False,
        "available": True,
        "gpu": False,
        "gpu_memory": None,
        "recommended": False,
        "embedding_model": "qwen3-vl-embedding-2b",
        "rerank_model": "qwen3-vl-reranker-2b",
    }
    fake_ml.device = "cuda"
    state = admin.get("/api/admin/multimodal").json()
    assert (state["gpu"], state["recommended"]) == (True, True)

    config = admin.get("/api/admin/config").json()
    mixed = admin.put(
        "/api/admin/config", json={**config, "embedding_model": "qwen3-vl-embedding-2b"}
    )
    assert mixed.status_code == 422 and "turn that on" in mixed.text

    on = admin.put("/api/admin/multimodal", json={"on": True})
    assert on.status_code == 200, on.text
    saved = load_config(db, settings)
    assert (saved.multimodal, saved.embedding_model, saved.rerank_model) == (
        True,
        "qwen3-vl-embedding-2b",
        "qwen3-vl-reranker-2b",
    )
    assert (saved.text_embedding_model, saved.text_rerank_model) == (
        "bge-m3",
        "bge-reranker-v2-m3",
    )
    assert (system.reembedding(db) or {}).get("model") == "qwen3-vl-embedding-2b"
    assert "paperus:queue_missing_embeddings" in queued(job_app)
    # Again: nothing changes. A text reranker refused while on.
    assert admin.put("/api/admin/multimodal", json={"on": True}).status_code == 200
    text_reranker = admin.put(
        "/api/admin/config",
        json={**on.json(), "rerank_model": "bge-reranker-v2-m3"},
    )
    assert text_reranker.status_code == 422 and "take images" in text_reranker.text

    off = admin.put("/api/admin/multimodal", json={"on": False})
    assert off.status_code == 200, off.text
    db.expire_all()
    saved = load_config(db, settings)
    assert (saved.multimodal, saved.embedding_model, saved.rerank_model) == (
        False,
        "bge-m3",
        "bge-reranker-v2-m3",
    )


def test_multimodal_without_an_ml_service(
    admin: TestClient, fake_ml: FakeML, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_ml.down = True
    state = admin.get("/api/admin/multimodal").json()
    assert (state["available"], state["recommended"]) == (False, False)
    assert admin.put("/api/admin/multimodal", json={"on": True}).status_code == 503
    fake_ml.down = False
    monkeypatch.setattr(FakeML, "TAKE_IMAGES", set())
    refused = admin.put("/api/admin/multimodal", json={"on": True})
    assert refused.status_code == 422 and "no models that take images" in refused.text
