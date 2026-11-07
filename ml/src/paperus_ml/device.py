"""Where models run: on the CPU, or on an NVIDIA GPU (CUDA) when the GPU
build of ONNX Runtime is installed (the ``-cuda`` image)."""

import ctypes
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import onnxruntime

log = logging.getLogger(__name__)

Device = Literal["cpu", "cuda"]
Choice = Literal["auto", "cpu", "cuda"]

CUDA = "CUDAExecutionProvider"
CPU = "CPUExecutionProvider"


class NoGPU(RuntimeError):
    pass


def gpu_problem() -> str | None:
    """Why models cannot run on a GPU here; None if they can."""
    if CUDA not in onnxruntime.get_available_providers():
        return "this ONNX Runtime has no CUDA support (use the -cuda image)"
    # The GPU build finds CUDA and cuDNN in the nvidia-* Python packages
    # only once they are loaded.
    preload = getattr(onnxruntime, "preload_dlls", None)
    if preload is not None:
        preload()
    if gpu_count():
        return None
    return "no NVIDIA GPU is reachable (e.g. not passed to the container)"


def choose(choice: Choice) -> Device:
    """``auto``: the GPU if ONNX Runtime can use one, else the CPU; ``cuda``
    insists on it."""
    if choice == "cpu":
        return "cpu"
    problem = gpu_problem()
    if problem is None:
        log.info("running models on the GPU")
        return "cuda"
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


def run_options(device: Device) -> onnxruntime.RunOptions:
    """On a GPU, give the memory a run needed back afterwards: a reranker's
    batch briefly needs gigabytes, and the card is shared with other models
    (and maybe a desktop)."""
    options = onnxruntime.RunOptions()
    if device == "cuda":
        options.add_run_config_entry("memory.enable_memory_arena_shrinkage", "gpu:0")
    return options


def providers(device: Device) -> list[str | tuple[str, dict[str, str]]]:
    """For ONNX Runtime; on the GPU, the CPU as a fallback (when the GPU
    cannot be used after all, e.g. no card reachable from the container)."""
    if device != "cuda":
        return [CPU]
    # Grow GPU memory by what is needed, not in doubling steps: several
    # models share a card of a few GB.
    return [(CUDA, {"arena_extend_strategy": "kSameAsRequested"}), CPU]


# The GPU image's CUDA 13 runs on cards from the RTX 20xx generation (Turing)
# on, whose PCI device ids start here, with this driver or newer.
FIRST_SUPPORTED_DEVICE = 0x1E00
DRIVER_NEEDED = 580


@dataclass(frozen=True)
class Card:
    name: str
    supported: bool
    """New enough for the GPU image (RTX 20xx generation or newer)."""


def host_cards(root: Path = Path("/")) -> list[Card]:
    """The machine's NVIDIA graphics cards, also when none is passed to this
    container: the kernel lists the PCI devices (and the NVIDIA driver its
    cards) in every container."""
    cards = []
    for device in sorted((root / "sys/bus/pci/devices").glob("*")):
        try:
            vendor, kind, ident = (
                (device / name).read_text().strip()
                for name in ("vendor", "class", "device")
            )
        except OSError:
            continue
        if vendor != "0x10de" or not kind.startswith("0x03"):
            continue
        cards.append(
            Card(
                _model_name(root, device.name) or f"NVIDIA graphics card ({ident})",
                int(ident, 16) >= FIRST_SUPPORTED_DEVICE,
            )
        )
    return cards


def _model_name(root: Path, bus: str) -> str | None:
    """The card's name, as the NVIDIA driver gives it (if installed)."""
    try:
        text = (root / "proc/driver/nvidia/gpus" / bus / "information").read_text()
    except OSError:
        return None
    found = re.search(r"^Model:\s*(.+?)\s*$", text, re.MULTILINE)
    return found[1] if found else None


def driver_version(root: Path = Path("/")) -> int | None:
    """The NVIDIA driver's major version, if one is loaded."""
    try:
        text = (root / "proc/driver/nvidia/version").read_text()
    except OSError:
        return None
    found = re.search(r"\s(\d{3,4})\.\d+", text)
    return int(found[1]) if found else None
