"""CPU or GPU, and which model file each uses."""

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
