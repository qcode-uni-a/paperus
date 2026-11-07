"""CPU or GPU, and which model file each uses."""

from dataclasses import replace
from typing import Any

import pytest

from paperus_ml import device
from paperus_ml.models import MODELS


def test_auto_uses_the_gpu_only_when_onnx_runtime_can(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        device.onnxruntime, "get_available_providers", lambda: [device.CPU]
    )
    assert device.choose("auto") == "cpu"
    with pytest.raises(device.NoGPU):
        device.choose("cuda")
    monkeypatch.setattr(
        device.onnxruntime,
        "get_available_providers",
        lambda: [device.CUDA, device.CPU],
    )
    monkeypatch.setattr(device.onnxruntime, "preload_dlls", lambda: None, raising=False)
    # The GPU build, but no card reachable (e.g. not passed to the container).
    monkeypatch.setattr(device, "gpu_count", lambda: 0)
    assert device.choose("auto") == "cpu"
    with pytest.raises(device.NoGPU):
        device.choose("cuda")
    monkeypatch.setattr(device, "gpu_count", lambda: 1)
    assert device.choose("auto") == "cuda"
    assert device.choose("cpu") == "cpu"
    assert [p if isinstance(p, str) else p[0] for p in device.providers("cuda")] == [
        device.CUDA,
        device.CPU,
    ]
    assert device.providers("cpu") == [device.CPU]


def test_vectors_are_named_by_the_file_they_come_from() -> None:
    """The usual (CPU) file keeps the model's name, so vectors stored before
    stay valid; another file is a different set of vectors."""
    arctic = MODELS["arctic-embed-m-v2"]
    assert arctic.onnx_file_for("cpu") == "onnx/model_quantized.onnx"
    assert arctic.vectors("cpu") == "arctic-embed-m-v2"
    assert arctic.onnx_file_for("cuda") == "onnx/model_fp16.onnx"
    assert arctic.vectors("cuda") == "arctic-embed-m-v2@fp16"
    # Already full precision: the same file and vectors on both.
    assert MODELS["bge-m3"].vectors("cuda") == "bge-m3"


class CudaRuntime:
    """libcudart, answering how many GPUs it sees."""

    def __init__(self, cards: int, error: int = 0) -> None:
        self.cards = cards
        self.error = error

    def cudaGetDeviceCount(self, count: Any) -> int:  # noqa: ANN401
        count._obj.value = self.cards
        return self.error


def test_gpus_are_counted_with_the_cuda_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtimes: dict[str, CudaRuntime] = {}

    def load(name: str) -> CudaRuntime:
        if name not in runtimes:
            raise OSError(f"{name}: cannot open shared object file")
        return runtimes[name]

    monkeypatch.setattr(device.ctypes, "CDLL", load)
    assert device.gpu_count() == 0  # no CUDA at all
    runtimes["libcudart.so.12"] = CudaRuntime(2)
    assert device.gpu_count() == 2
    runtimes["libcudart.so.13"] = CudaRuntime(1, error=100)  # no driver
    assert device.gpu_count() == 0


def test_gpu_memory_is_given_back_after_each_run() -> None:
    entry = "memory.enable_memory_arena_shrinkage"
    assert device.run_options("cuda").get_run_config_entry(entry) == "gpu:0"
    with pytest.raises(RuntimeError):
        device.run_options("cpu").get_run_config_entry(entry)


def test_other_files_are_other_vectors() -> None:
    bge = MODELS["bge-m3"]
    assert replace(bge, gpu_onnx_file="onnx/model_int8.onnx").vectors("cuda") == (
        "bge-m3@int8"
    )
    # Full precision on the GPU, a quantized file on the CPU.
    assert MODELS["ms-marco-minilm-l6"].vectors("cuda") == "ms-marco-minilm-l6@fp32"
