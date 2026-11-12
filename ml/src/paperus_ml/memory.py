"""How much memory there is, and how much a model takes once loaded: RAM
from the system, GPU memory from NVIDIA's driver library (NVML), so paperus
can say whether the chosen models fit together. Measured, not guessed: a
model takes more than its files (its working memory), and how much more
depends on the model and the machine."""

import ctypes
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from paperus_ml.device import Device

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Memory:
    total: int
    free: int
    """Available for new use (RAM: MemAvailable, with what caches would give
    up); bytes."""


def ram() -> Memory | None:
    """The machine's RAM (a container sees the host's), if the system says."""
    try:
        text = Path("/proc/meminfo").read_text()
    except OSError:
        return None
    values = {
        k: int(v) * 1024 for k, v in re.findall(r"^(\w+):\s+(\d+) kB", text, re.M)
    }
    if "MemTotal" not in values:
        return None
    return Memory(
        values["MemTotal"], values.get("MemAvailable", values.get("MemFree", 0))
    )


class _NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


def gpu() -> Memory | None:
    """The first NVIDIA GPU's memory (all programs' use counted), if its
    driver's library is there."""
    try:
        nvml = ctypes.CDLL("libnvidia-ml.so.1")
    except OSError:
        return None
    handle = ctypes.c_void_p()
    info = _NvmlMemory()
    if (
        nvml.nvmlInit_v2() != 0
        or nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0
        or nvml.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(info)) != 0
    ):
        return None
    return Memory(int(info.total), int(info.free))


def process_bytes() -> int | None:
    """This process's resident memory, if the system says."""
    try:
        resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return resident_pages * os.sysconf("SC_PAGE_SIZE")


def in_use(device: Device) -> int | None:
    """What a model loading now adds to: the GPU's used memory on the GPU,
    else this process's."""
    if device == "cuda":
        memory = gpu()
        return None if memory is None else memory.total - memory.free
    return process_bytes()


class Measured:
    """How much each model took once loaded, per file (``ModelSpec.vectors``:
    the GPU's and the CPU's differ), kept in the model cache across
    restarts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.sizes: dict[str, int] = {
                str(k): int(v) for k, v in json.loads(path.read_text()).items()
            }
        except (OSError, ValueError, AttributeError):
            self.sizes = {}

    def get(self, variant: str) -> int | None:
        return self.sizes.get(variant)

    def record(self, variant: str, size: int) -> None:
        self.sizes[variant] = size
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.sizes, indent=1, sort_keys=True))
        except OSError:
            log.warning("could not keep the models' memory in %s", self.path)
