"""The administration's ML models, when the ML service is loading or does
not know a model, and the readable copy being switched on."""

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App

from tests.conftest import FakeML
from tests.test_admin import queued


class LoadingML(FakeML):
    """An ML service still downloading its models, which knows only its own."""

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/speed"):
            return httpx2.Response(503, json={"detail": "loading"})
        if request.method == "DELETE" and request.url.path != "/models/bge-reranker":
            return httpx2.Response(404, json={"detail": "no such model"})
        return super().__call__(request)


@pytest.fixture
def fake_ml() -> FakeML:
    return LoadingML()


def test_speed_while_loading(admin: TestClient) -> None:
    speed = admin.post("/api/admin/ml/models/bge-m3/speed")
    assert speed.status_code == 200
    assert speed.json()["loading"] is True


def test_deleting_unknown_models(admin: TestClient, fake_ml: FakeML) -> None:
    unknown = admin.delete("/api/admin/ml/models/nope")
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "no such model")
    assert admin.delete("/api/admin/ml/models/bge-reranker").status_code == 204
    fake_ml.down = True
    assert admin.delete("/api/admin/ml/models/bge-reranker").status_code == 503


def test_switching_the_readable_copy_on(admin: TestClient, job_app: App) -> None:
    config = admin.get("/api/admin/config").json()
    assert admin.put("/api/admin/config", json=config).status_code == 200
    assert "paperus:readable_copy" not in queued(job_app)
    on = admin.put("/api/admin/config", json={**config, "copy_enabled": True})
    assert on.status_code == 200, on.text
    assert "paperus:readable_copy" in queued(job_app)
