"""Settings, read from environment variables prefixed with ``PAPERUS_ML_``."""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAPERUS_ML_", env_file=".env")

    # Downloaded models, one folder per task and model:
    # <cache>/embedding/bge-m3/. "/cache" (a volume) in the container.
    cache_path: Path = Field(default_factory=lambda: default_cache_path())
    # Models that came with the image (read-only, same layout), used instead
    # of downloading them: the recommended ones, in /models.
    builtin_path: Path | None = None
    # Shared secret: requests need "Authorization: Bearer <token>" when set.
    token: str | None = None
    # Unload a model after this many idle seconds (0: never).
    model_ttl: int = 300
    # Models to load at startup, never unloaded, e.g. ["bge-m3"].
    preload: list[str] = []
    # "auto": an NVIDIA GPU if the GPU build of ONNX Runtime is installed
    # (the -cuda image), else the CPU; "cpu" or "cuda" to insist.
    device: Literal["auto", "cpu", "cuda"] = "auto"
    # ONNX Runtime threads per model; 0 lets ONNX Runtime decide.
    intra_op_threads: int = 0
    # Most texts and tokens per inference batch (memory grows with both).
    max_batch_texts: int = 32
    max_batch_tokens: int = 16384
    # How long a request waits for a model that is still loading before the
    # service answers 503 "loading" (the model keeps loading meanwhile).
    load_wait: float = 2.0
    # Prometheus metrics on this port (inside the container network); off
    # unless set, e.g. 9465.
    metrics_port: int | None = None


def default_cache_path() -> Path:
    """~/.cache/paperus-ml, or under $XDG_CACHE_HOME."""
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "paperus-ml"
