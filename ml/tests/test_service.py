from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperus_ml.config import Settings
from paperus_ml.encoder import Encoder
from paperus_ml.main import create_app
from paperus_ml.manager import ModelManager, UnknownModel
from paperus_ml.models import MODELS, ModelSpec
from tests.tiny_model import DIMENSIONS, write_tiny_model


@pytest.fixture
def tiny(tmp_path: Path) -> Encoder:
    return Encoder(write_tiny_model(tmp_path), tmp_path)


class CountingLoader:
    def __init__(self, encoder: Encoder) -> None:
        self.encoder = encoder
        self.loads: list[str] = []

    def __call__(self, spec: ModelSpec) -> Encoder:
        self.loads.append(spec.name)
        return self.encoder


def test_manager_loads_once_and_unloads_idle(tiny: Encoder) -> None:
    loader = CountingLoader(tiny)
    manager = ModelManager(Settings(model_ttl=60), loader)
    assert manager.get("bge-m3") is tiny
    assert manager.get("bge-m3") is tiny
    assert loader.loads == ["bge-m3"]
    assert manager.unload_idle() == []
    assert manager.unload_idle(now=10**9) == ["bge-m3"]
    manager.get("bge-m3")
    assert loader.loads == ["bge-m3", "bge-m3"]
    with pytest.raises(UnknownModel):
        manager.get("nope")


def test_preloaded_models_stay(tiny: Encoder) -> None:
    manager = ModelManager(
        Settings(model_ttl=60, preload=["multilingual-e5-small"]), CountingLoader(tiny)
    )
    manager.preload()
    assert manager.unload_idle(now=10**9) == []
    assert manager.loaded() == ["multilingual-e5-small"]


@pytest.fixture
def client(tiny: Encoder) -> Iterator[TestClient]:
    manager = ModelManager(Settings(), CountingLoader(tiny))
    with TestClient(create_app(Settings(token="s3cret"), manager)) as client:
        client.headers["Authorization"] = "Bearer s3cret"
        yield client


def test_embed(client: TestClient) -> None:
    response = client.post(
        "/embed",
        json={"model": "bge-m3", "kind": "query", "texts": ["drought", "rain"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "bge-m3"
    assert body["dimensions"] == DIMENSIONS
    assert len(body["embeddings"]) == 2


def test_token_required(client: TestClient) -> None:
    body = {"model": "bge-m3", "texts": ["x"]}
    assert (
        client.post(
            "/embed", json=body, headers={"Authorization": "Bearer no"}
        ).status_code
        == 401
    )
    assert (
        client.post("/embed", json=body, headers={"Authorization": ""}).status_code
        == 401
    )
    assert client.get("/ping").json() == "pong"


def test_bad_requests(client: TestClient) -> None:
    assert (
        client.post("/embed", json={"model": "nope", "texts": ["x"]}).status_code == 404
    )
    assert (
        client.post("/embed", json={"model": "bge-m3", "texts": []}).status_code == 422
    )
    too_many = {"model": "bge-m3", "texts": ["x"] * 257}
    assert client.post("/embed", json=too_many).status_code == 422


def test_models_listing(client: TestClient) -> None:
    listed = {m["name"]: m for m in client.get("/models").json()}
    assert set(listed) == set(MODELS)
    assert listed["bge-m3"]["dimensions"] == 1024


def test_cache_layout_and_delete(tmp_path: Path, tiny: Encoder) -> None:
    manager = ModelManager(Settings(cache_path=tmp_path), CountingLoader(tiny))
    spec = MODELS["bge-m3"]
    directory = manager.model_dir(spec)
    assert directory == tmp_path / "embedding" / "bge-m3"
    assert manager.cached_bytes(spec) is None
    (directory / "onnx").mkdir(parents=True)
    (directory / spec.onnx_file).write_bytes(b"x" * 10)
    assert manager.cached_bytes(spec) == 10

    manager.get("bge-m3")
    with TestClient(create_app(Settings(cache_path=tmp_path), manager)) as client:
        listed = {m["name"]: m for m in client.get("/models").json()}
        assert listed["bge-m3"]["cached_bytes"] == 10
        assert listed["bge-m3"]["loaded"] is True
        assert client.delete("/models/bge-m3").status_code == 204
        assert client.delete("/models/nope").status_code == 404
    assert not directory.exists()
    assert manager.loaded() == []


def test_default_cache_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv("PAPERUS_ML_CACHE_PATH", raising=False)
    assert Settings().cache_path == tmp_path / "paperus-ml"
