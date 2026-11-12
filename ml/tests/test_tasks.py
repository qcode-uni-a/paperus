"""Reranking and OCR through the service, downloading models, and running
the service (CLI, metrics port, unloading idle models)."""

import os
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from paperus_ml import cli, main, manager, metrics
from paperus_ml.config import Settings
from paperus_ml.device import Device
from paperus_ml.encoder import Encoder
from paperus_ml.main import create_app, usable_cores
from paperus_ml.manager import Model, ModelManager
from paperus_ml.models import MODELS, ModelSpec
from paperus_ml.ocr import Reader
from paperus_ml.rerank import Reranker
from tests.test_ocr import TWO_COLUMNS, page
from tests.tiny_model import (
    tiny_rerank_score,
    write_tiny_model,
    write_tiny_ocr,
    write_tiny_reranker,
)


class TinyModels:
    """Loads a tiny model of the task asked for, whichever model it is."""

    def __init__(self, directory: Path) -> None:
        for task in ("embedding", "rerank", "ocr"):
            (directory / task).mkdir(parents=True)
        self.encoder = Encoder(
            write_tiny_model(directory / "embedding"), directory / "embedding"
        )
        self.reranker = Reranker(
            write_tiny_reranker(directory / "rerank"), directory / "rerank"
        )
        self.reader = Reader(write_tiny_ocr(directory / "ocr"), directory / "ocr")
        self.loads: list[str] = []

    def __call__(self, spec: ModelSpec, device: Device = "cpu") -> Model:
        self.loads.append(spec.name)
        return {"embedding": self.encoder, "rerank": self.reranker}.get(
            spec.task, self.reader
        )


@pytest.fixture
def tiny_models(tmp_path: Path) -> TinyModels:
    return TinyModels(tmp_path / "tiny")


@pytest.fixture
def client(tiny_models: TinyModels) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(), ModelManager(Settings(), tiny_models))) as c:
        yield c


def requests(model: str, kind: str, outcome: str) -> float:
    labels = {"model": model, "kind": kind, "outcome": outcome}
    return REGISTRY.get_sample_value("paperus_ml_requests_total", labels) or 0


def test_rerank(client: TestClient) -> None:
    passages = ["cooking pasta", "drought rivers", "rain"]
    before = requests("ms-marco-minilm-l6", "rerank", "ok")
    response = client.post(
        "/rerank",
        json={"model": "ms-marco-minilm-l6", "query": "drought", "passages": passages},
    )
    assert response.status_code == 200
    assert response.json()["scores"] == pytest.approx(
        [tiny_rerank_score("drought", p) for p in passages]
    )
    assert requests("ms-marco-minilm-l6", "rerank", "ok") == before + 1
    # Failed requests count too.
    before = requests("nope", "rerank", "error")
    body = {"model": "nope", "query": "rain", "passages": ["rain"]}
    assert client.post("/rerank", json=body).status_code == 404
    assert requests("nope", "rerank", "error") == before + 1


def test_ocr(client: TestClient) -> None:
    response = client.post("/ocr/pp-ocrv6-small", content=page(TWO_COLUMNS))
    assert response.status_code == 200
    read = response.json()
    assert (read["model"], read["width"], read["height"]) == (
        "pp-ocrv6-small",
        600,
        800,
    )
    assert read["text"].startswith("x" * 12 + "\n")
    assert [line["text"] for line in read["lines"]] == read["text"].split()
    assert len(read["lines"][0]["box"]) == 4
    not_an_image = client.post("/ocr/pp-ocrv6-small", content=b"not an image")
    assert not_an_image.status_code == 422
    too_big = b"x" * (main.MAX_IMAGE_BYTES + 1)
    assert client.post("/ocr/pp-ocrv6-small", content=too_big).status_code == 413


def test_ocr_while_loading(tiny_models: TinyModels) -> None:
    release = threading.Event()

    def slow(spec: ModelSpec, device: Device = "cpu") -> Model:
        release.wait(5)
        return tiny_models(spec)

    settings = Settings(load_wait=0.01)
    with TestClient(create_app(settings, ModelManager(settings, slow))) as client:
        before = requests("pp-ocrv6-small", "ocr", "loading")
        response = client.post("/ocr/pp-ocrv6-small", content=page([]))
        assert response.status_code == 503
        assert requests("pp-ocrv6-small", "ocr", "loading") == before + 1
        release.set()


def test_measure_speed_of_rerankers_and_ocr(client: TestClient) -> None:
    rerank = client.post("/models/ms-marco-minilm-l6/speed").json()
    assert rerank["passages"] == 48 and rerank["passages_per_second"] > 0
    ocr = client.post("/models/pp-ocrv6-small/speed").json()
    assert ocr["passages"] == main.OCR_SPEED_PAGES
    assert ocr["passages_per_second"] > 0


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Hugging Face Hub, serving tiny models for the repositories of
    ms-marco-minilm-l6 and pp-ocrv6-small; the repositories downloaded."""
    source = tmp_path / "hub"
    (source / "ocr").mkdir(parents=True)
    write_tiny_reranker(source)
    write_tiny_ocr(source / "ocr")
    ocr = MODELS["pp-ocrv6-small"]
    assert ocr.detector is not None
    files = {
        MODELS["ms-marco-minilm-l6"].repo: (
            source / "reranker.onnx",
            source / "tokenizer.json",
        ),
        ocr.repo: (
            source / "ocr" / "reader.onnx",
            source / "ocr" / "reader.yml",
        ),
        ocr.detector.repo: (
            source / "ocr" / "det" / "detector.onnx",
            None,
        ),
    }
    downloaded: list[str] = []

    def snapshot_download(
        repo_id: str, *, revision: str, local_dir: Path, allow_patterns: list[str]
    ) -> str:
        """The model file (and its other parts) first, then the tokenizer."""
        downloaded.append(repo_id)
        model, tokenizer = files[repo_id]
        for pattern in allow_patterns:
            target = Path(local_dir) / pattern.rstrip("*")
            target.parent.mkdir(parents=True, exist_ok=True)
            from_file = model if pattern.endswith("*") else tokenizer
            assert from_file is not None
            shutil.copy(from_file, target)
        return str(local_dir)

    monkeypatch.setattr(manager, "snapshot_download", snapshot_download)
    return downloaded


def test_models_are_downloaded_into_the_cache(tmp_path: Path, hub: list[str]) -> None:
    cache = tmp_path / "cache"
    models = ModelManager(Settings(cache_path=cache, device="cpu"))
    reranker = models.get("ms-marco-minilm-l6")
    assert isinstance(reranker, Reranker)
    assert reranker.score("rain", ["rain"]) == [tiny_rerank_score("rain", "rain")]
    assert (cache / "rerank" / "ms-marco-minilm-l6" / "tokenizer.json").is_file()

    reader = models.get("pp-ocrv6-small")
    assert isinstance(reader, Reader)
    assert reader.read(page([(40, 40, 3, 0)])).text == "xxx"
    assert (cache / "ocr" / "pp-ocrv6-small" / "det" / "inference.onnx").is_file()
    assert hub == [
        "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "PaddlePaddle/PP-OCRv6_small_rec_onnx",
        "PaddlePaddle/PP-OCRv6_small_det_onnx",
    ]
    cached = models.cached_bytes(MODELS["pp-ocrv6-small"])
    assert cached is not None and cached > 0


def test_without_a_usable_gpu_models_run_on_the_cpu(
    tmp_path: Path, hub: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    models = ModelManager(Settings(cache_path=tmp_path / "cache", device="cpu"))
    # As if a GPU had been found, but ONNX Runtime cannot use it after all.
    models.device = "cuda"
    with pytest.warns(UserWarning, match="CUDAExecutionProvider"):
        reranker = models.get("ms-marco-minilm-l6")
    assert reranker.device == "cpu"
    assert "no usable GPU" in caplog.text
    # The GPU's file (full precision) was downloaded.
    folder = tmp_path / "cache" / "rerank" / "ms-marco-minilm-l6"
    assert (folder / "onnx" / "model.onnx").is_file()


def test_simultaneous_requests_load_a_model_once(tiny_models: TinyModels) -> None:
    release = threading.Event()

    def slow(spec: ModelSpec, device: Device = "cpu") -> Model:
        release.wait(5)
        return tiny_models(spec)

    models = ModelManager(Settings(), slow)
    got: list[Model] = []
    threads = [
        threading.Thread(target=lambda: got.append(models.get("bge-m3")))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    time.sleep(0.05)  # both waiting: one loading, one for it
    release.set()
    for thread in threads:
        thread.join()
    assert got == [tiny_models.encoder, tiny_models.encoder]
    assert tiny_models.loads == ["bge-m3"]


def test_idle_models_stay_when_busy_or_without_a_ttl(tiny_models: TinyModels) -> None:
    models = ModelManager(Settings(model_ttl=60), tiny_models)
    models.get("bge-m3")
    # Busy (e.g. loading again with other threads): checked next time.
    with models._locks["bge-m3"]:
        assert models.unload_idle(now=1e12) == []
    assert models.unload_idle(now=1e12) == ["bge-m3"]
    forever = ModelManager(Settings(model_ttl=0), tiny_models)
    forever.get("bge-m3")
    assert forever.unload_idle(now=1e12) == []


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_metrics_port_and_unloading_idle_models(
    tiny_models: TinyModels, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The metrics server starts with the service (once per process; it
    keeps running), and idle models are unloaded in the background."""
    monkeypatch.setattr(metrics, "_started", False)
    monkeypatch.setattr(main, "UNLOAD_CHECK_SECONDS", 0.05)
    port = free_port()
    settings = Settings(metrics_port=port, model_ttl=1)
    models = ModelManager(settings, tiny_models)
    with TestClient(create_app(settings, models)) as client:
        client.post("/embed", json={"model": "bge-m3", "texts": ["rain"]})
        scraped = httpx2.get(f"http://127.0.0.1:{port}/metrics").text
        assert 'paperus_ml_model_loaded{model="bge-m3"} 1.0' in scraped
        # A second service in the same process shares the metrics server.
        metrics.serve(port, metrics.ModelsCollector(list, list))
        for _ in range(100):
            if not models.loaded():
                break
            time.sleep(0.05)
        assert models.loaded() == []


def test_usable_cores(monkeypatch: pytest.MonkeyPatch) -> None:
    assert 1 <= usable_cores() <= (os.cpu_count() or 1)
    # Not on Linux: all of them.
    monkeypatch.delattr(os, "sched_getaffinity")
    assert usable_cores() == (os.cpu_count() or 1)


def test_cli_runs_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    started: dict[str, object] = {}

    def run(app: str, **options: object) -> None:
        started.update(options, app=app)

    monkeypatch.setattr(cli.uvicorn, "run", run)
    cli.main(["--host", "0.0.0.0", "--port", "3999"])
    assert started == {
        "app": "paperus_ml.main:create_app",
        "factory": True,
        "host": "0.0.0.0",
        "port": 3999,
    }
    cli.main([])
    assert (started["host"], started["port"]) == ("127.0.0.1", 3003)
