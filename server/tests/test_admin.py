import uuid

from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy.orm import Session

from paperus.config import Settings
from paperus.embedding import embed_file
from paperus.processing import process_file
from paperus.storage import BlobStore
from paperus.system import load_config
from tests.conftest import FakeML


def queued(job_app: App) -> list[str]:
    assert isinstance(job_app.connector, InMemoryConnector)
    return [j["task_name"] for j in job_app.connector.jobs.values()]


def test_admins_only(logged_in: TestClient) -> None:
    for path in ["/api/admin/config", "/api/admin/ml", "/api/admin/stats"]:
        assert logged_in.get(path).status_code == 403


def test_change_embedding_model(
    admin: TestClient, db: Session, settings: Settings, job_app: App
) -> None:
    assert admin.get("/api/admin/config").json() == {"embedding_model": "bge-m3"}
    response = admin.put(
        "/api/admin/config", json={"embedding_model": "multilingual-e5-small"}
    )
    assert response.status_code == 200
    assert load_config(db, settings).embedding_model == "multilingual-e5-small"
    # The library is re-embedded in the background.
    assert queued(job_app) == ["paperus:queue_missing_embeddings"]

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
    assert [m["name"] for m in status["models"]] == FakeML.MODELS
    fake_ml.down = True
    status = admin.get("/api/admin/ml").json()
    assert status["services"][0]["ok"] is False
    assert status["models"] == []


def test_measure_speed(admin: TestClient, fake_ml: FakeML) -> None:
    speed = admin.post("/api/admin/ml/models/bge-m3/speed").json()
    assert (speed["model"], speed["passages_per_second"]) == ("bge-m3", 8.0)
    assert admin.post("/api/admin/ml/models/nope/speed").status_code == 503
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


def test_run_jobs(admin: TestClient, job_app: App) -> None:
    assert admin.post("/api/admin/jobs/embeddings").status_code == 202
    assert admin.post("/api/admin/jobs/text").status_code == 202
    assert admin.post("/api/admin/jobs/nope").status_code == 404
    assert sorted(queued(job_app)) == [
        "paperus:queue_missing_embeddings",
        "paperus:queue_pending_files",
    ]
