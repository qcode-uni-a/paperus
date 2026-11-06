import threading
import time
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
    assert body["vectors"] == "bge-m3"
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
    # What an admin needs for choosing one.
    arctic = listed["arctic-embed-m-v2"]
    assert arctic["licence"] == "Apache-2.0" and arctic["download_mb"] == 311
    assert arctic["scores"] == {"en": 58.4, "de": 55.2, "multilingual": 54.8}
    assert arctic["benchmarks"]["de"] == "Retrieval, German (MTEB deu v1)"
    assert all(m["description"] and m["licence"] for m in listed.values())


def test_measure_speed(client: TestClient) -> None:
    speed = client.post("/models/bge-m3/speed").json()
    assert speed["passages"] == 48 and speed["passages_per_second"] > 0
    assert client.post("/models/nope/speed").status_code == 404


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


def test_config_from_paperus(tiny: Encoder) -> None:
    loader = CountingLoader(tiny)
    manager = ModelManager(Settings(), loader)
    with TestClient(create_app(Settings(), manager)) as client:
        state = client.get("/config").json()
        assert (state["threads"], state["keep"], state["loaded"]) == (0, [], [])
        assert state["cores"] >= 1
        # The model in use is kept and loads in the background.
        state = client.put("/config", json={"threads": 2, "keep": ["bge-m3"]}).json()
        assert (state["threads"], state["keep"]) == (2, ["bge-m3"])
        assert manager.loaded() == ["bge-m3"] and loader.loads == ["bge-m3"]
        # Other threads: models load again with them.
        client.put("/config", json={"threads": 4, "keep": ["bge-m3"]})
        assert loader.loads == ["bge-m3", "bge-m3"]
        # The same again changes nothing.
        client.put("/config", json={"threads": 4, "keep": ["bge-m3"]})
        assert loader.loads == ["bge-m3", "bge-m3"]
        assert (
            client.put("/config", json={"threads": 4, "keep": ["x"]}).status_code == 404
        )
    # Kept models are not unloaded when idle.
    assert manager.unload_idle(now=1e12) == []


class SlowLoader(CountingLoader):
    """Loads only when released, like a long download."""

    def __init__(self, encoder: Encoder) -> None:
        super().__init__(encoder)
        self.release = threading.Event()

    def __call__(self, spec: ModelSpec) -> Encoder:
        self.release.wait(5)
        return super().__call__(spec)


def test_requests_do_not_wait_for_a_download(tiny: Encoder) -> None:
    loader = SlowLoader(tiny)
    manager = ModelManager(Settings(load_wait=0.05), loader)
    with TestClient(create_app(Settings(load_wait=0.05), manager)) as client:
        body = {"model": "bge-m3", "texts": ["rain"]}
        response = client.post("/embed", json=body)
        assert response.status_code == 503 and response.headers["Retry-After"]
        assert client.get("/config").json()["loading"] == ["bge-m3"]
        assert client.post("/models/bge-m3/speed").status_code == 503
        assert client.get("/ping").status_code == 200  # still answers
        loader.release.set()
        for _ in range(100):  # the background load finishes
            if manager.loaded() == ["bge-m3"]:
                break
            time.sleep(0.01)
        assert client.post("/embed", json=body).status_code == 200
        assert loader.loads == ["bge-m3"]  # loaded once


def test_failed_loads_are_reported(tiny: Encoder) -> None:
    def failing(spec: ModelSpec) -> Encoder:
        raise OSError("disk full")

    manager = ModelManager(Settings(load_wait=1), failing)
    with TestClient(create_app(Settings(load_wait=1), manager)) as client:
        response = client.post("/embed", json={"model": "bge-m3", "texts": ["x"]})
        assert response.status_code == 502
        assert "disk full" in response.json()["detail"]


def test_new_threads_reload_when_used(tiny: Encoder) -> None:
    loader = CountingLoader(tiny)
    manager = ModelManager(Settings(intra_op_threads=3), loader)
    manager.get("bge-m3")
    assert manager.configure(threads=5, keep=["bge-m3"]) == ["bge-m3"]
    assert manager.loaded() == ["bge-m3"]  # still there for running requests
    manager.load_kept()
    assert loader.loads == ["bge-m3", "bge-m3"]
    # None: back to the service's own setting.
    manager.configure(threads=None, keep=[])
    assert manager.threads == 3


def test_metrics(client: TestClient) -> None:
    from prometheus_client import REGISTRY, CollectorRegistry, generate_latest

    from paperus_ml.metrics import ModelsCollector

    def count() -> float:
        labels = {"model": "bge-m3", "kind": "passage", "outcome": "ok"}
        return REGISTRY.get_sample_value("paperus_ml_requests_total", labels) or 0

    before = count()
    client.post("/embed", json={"model": "bge-m3", "texts": ["rain", "snow"]})
    assert count() == before + 1
    registry = CollectorRegistry()
    registry.register(
        ModelsCollector(lambda: ["bge-m3"], lambda: ["arctic-embed-m-v2"])
    )
    text = generate_latest(registry).decode()
    assert 'paperus_ml_model_loaded{model="bge-m3"} 1.0' in text
    assert 'paperus_ml_model_loaded{model="arctic-embed-m-v2"} 0.5' in text
