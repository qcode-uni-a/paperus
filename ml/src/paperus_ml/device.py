"""Where models run: on the CPU, or on an NVIDIA GPU (CUDA) when the GPU
build of ONNX Runtime is installed (the ``-cuda`` image)."""

import ctypes
import logging
from typing import Literal

import onnxruntime

log = logging.getLogger(__name__)

Device = Literal["cpu", "cuda"]
Choice = Literal["auto", "cpu", "cuda"]

CUDA = "CUDAExecutionProvider"
CPU = "CPUExecutionProvider"


class NoGPU(RuntimeError):
    pass


def choose(choice: Choice) -> Device:
    """``auto``: the GPU if ONNX Runtime can use one, else the CPU; ``cuda``
    insists on it."""
    if choice == "cpu":
        return "cpu"
    if CUDA not in onnxruntime.get_available_providers():
        problem = "this ONNX Runtime has no CUDA support (use the -cuda image)"
    else:
        # The GPU build finds CUDA and cuDNN in the nvidia-* Python packages
        # only once they are loaded.
        preload = getattr(onnxruntime, "preload_dlls", None)
        if preload is not None:
            preload()
        cards = gpu_count()
        if cards:
            log.info("running models on the GPU (%d found)", cards)
            return "cuda"
        problem = "no NVIDIA GPU is reachable (e.g. not passed to the container)"
    if choice == "cuda":
        raise NoGPU(f"PAPERUS_ML_DEVICE=cuda, but {problem}")
    if CUDA in onnxruntime.get_available_providers():
        log.warning("running models on the CPU: %s", problem)
    return "cpu"


def gpu_count() -> int:
    """NVIDIA GPUs the CUDA runtime (loaded by ONNX Runtime) can use."""
    for name in (
        "libcudart.so.13",
        "libcudart.so.12",
        "cudart64_13.dll",
        "cudart64_12.dll",
    ):
        try:
            runtime = ctypes.CDLL(name)
        except OSError:
            continue
        count = ctypes.c_int(0)
        if runtime.cudaGetDeviceCount(ctypes.byref(count)) != 0:
            return 0
        return count.value
    return 0


def providers(device: Device) -> list[str | tuple[str, dict[str, str]]]:
    """For ONNX Runtime; on the GPU, the CPU as a fallback (when the GPU
    cannot be used after all, e.g. no card reachable from the container)."""
    if device != "cuda":
        return [CPU]
    # Grow GPU memory by what is needed, not in doubling steps: several
    # models share a card of a few GB.
    return [(CUDA, {"arena_extend_strategy": "kSameAsRequested"}), CPU]
