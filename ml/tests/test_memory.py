"""Memory: the machine's and a model's once loaded; when a model does not
fit, the others make room, and a reranker or OCR model runs on the CPU."""

import ctypes
from pathlib import Path
from typing import Any, cast

import pytest

from paperus_ml import memory
from paperus_ml.config import Settings
from paperus_ml.device import Device
from paperus_ml.encoder import Encoder
from paperus_ml.manager import ModelManager, out_of_memory
from paperus_ml.models import ModelSpec
from tests.tiny_model import write_tiny_model


@pytest.fixture
def tiny(tmp_path: Path) -> Encoder:
    return Encoder(write_tiny_model(tmp_path), tmp_path)


def test_the_machines_memory() -> None:
    ram = memory.ram()
    assert ram is not None and 0 < ram.free <= ram.total
    assert (memory.process_bytes() or 0) > 0
    assert memory.in_use("cpu") == memory.process_bytes() or memory.in_use("cpu")


def test_without_proc(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(self: Path) -> str:
        raise OSError("no /proc here")

    monkeypatch.setattr(Path, "read_text", missing)
    assert memory.ram() is None
    assert memory.process_bytes() is None


def test_the_gpus_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    class Nvml:
        def nvmlInit_v2(self) -> int:
            return 0

        def nvmlDeviceGetHandleByIndex_v2(self, index: int, handle: object) -> int:
            return 0

        def nvmlDeviceGetMemoryInfo(self, handle: object, info: object) -> int:
            target = cast(Any, info)._obj  # what byref() points to
            target.total, target.free = 8 * 2**30, 6 * 2**30
            return 0

    monkeypatch.setattr(ctypes, "CDLL", lambda name: Nvml())
    assert memory.gpu() == memory.Memory(8 * 2**30, 6 * 2**30)
    assert memory.in_use("cuda") == 2 * 2**30

    def no_driver(name: str) -> None:
        raise OSError("no NVIDIA driver")

    monkeypatch.setattr(ctypes, "CDLL", no_driver)
    assert memory.gpu() is None
    assert memory.in_use("cuda") is None


def test_measured_sizes_kept(tmp_path: Path) -> None:
    path = tmp_path / "cache" / "memory.json"
    memory.Measured(path).record("bge-m3@fp16", 1234)
    assert memory.Measured(path).get("bge-m3@fp16") == 1234
    path.write_text("not json")
    assert memory.Measured(path).get("bge-m3@fp16") is None
    # Not writable: kept for now all the same.
    blocked = memory.Measured(tmp_path / "cache" / "memory.json" / "x")
    blocked.record("x", 1)
    assert blocked.get("x") == 1


class Loader:
    """Fails for lack of memory ``fail`` times (per model, on the GPU only
    if ``gpu_only``), then gives the tiny model; counts its loads."""

    def __init__(self, tiny: Encoder, fail: int, *, gpu_only: bool = False) -> None:
        self.tiny, self.fail, self.gpu_only = tiny, fail, gpu_only
        self.loads: list[tuple[str, Device]] = []

    def __call__(self, spec: ModelSpec, device: Device) -> Encoder:
        self.loads.append((spec.name, device))
        if self.fail and (device == "cuda" or not self.gpu_only):
            self.fail -= 1
            raise RuntimeError("Failed to allocate memory for requested buffer")
        return self.tiny


def gpu_manager(tmp_path: Path, loader: Loader) -> ModelManager:
    models = ModelManager(Settings(cache_path=tmp_path), loader)
    models.device = "cuda"
    return models


def test_out_of_memory() -> None:
    assert out_of_memory(MemoryError())
    assert out_of_memory(RuntimeError("CUDA error: out of memory"))
    assert not out_of_memory(RuntimeError("file not found"))


def test_others_make_room(tmp_path: Path, tiny: Encoder) -> None:
    loader = Loader(tiny, fail=0)
    models = gpu_manager(tmp_path, loader)
    models.configure(threads=None, keep=["bge-m3"])
    models.get("bge-m3")
    models.get("ms-marco-minilm-l6")
    loader.fail = 1  # the next load does not fit until the reranker goes
    models.get("pp-ocrv6-small")
    assert models.loaded() == ["bge-m3", "pp-ocrv6-small"]  # the kept one stays
    assert models.on_cpu == {}


def test_a_reranker_on_the_cpu_if_the_gpu_is_full(
    tmp_path: Path, tiny: Encoder
) -> None:
    loader = Loader(tiny, fail=5, gpu_only=True)
    models = gpu_manager(tmp_path, loader)
    models.get("ms-marco-minilm-l6")
    assert loader.loads[-1] == ("ms-marco-minilm-l6", "cpu")
    assert models.on_cpu == {"ms-marco-minilm-l6": "not enough GPU memory"}


def test_a_search_model_does_not_move_to_the_cpu(tmp_path: Path, tiny: Encoder) -> None:
    loader = Loader(tiny, fail=5, gpu_only=True)
    models = gpu_manager(tmp_path, loader)
    with pytest.raises(RuntimeError, match="allocate memory"):
        models.get("bge-m3")
    assert all(device == "cuda" for _, device in loader.loads)
    # Another error is not about memory: raised as it is.
    loader.fail, loader.gpu_only = 0, False

    def broken(spec: ModelSpec, device: Device) -> Encoder:
        raise FileNotFoundError("model.onnx")

    other = ModelManager(Settings(cache_path=tmp_path), broken)
    with pytest.raises(FileNotFoundError):
        other.get("bge-m3")


def test_what_a_model_takes_is_measured(
    tmp_path: Path, tiny: Encoder, monkeypatch: pytest.MonkeyPatch
) -> None:
    readings = iter([1_000, 51_000])
    monkeypatch.setattr(memory, "in_use", lambda device: next(readings))
    models = ModelManager(Settings(cache_path=tmp_path), Loader(tiny, fail=0))
    models.get("bge-m3")
    assert models.measured.get("bge-m3") == 50_000
