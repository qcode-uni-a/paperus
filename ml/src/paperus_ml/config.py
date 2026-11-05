"""Settings, read from environment variables prefixed with ``PAPERUS_ML_``."""

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAPERUS_ML_", env_file=".env")

    # Downloaded models, one folder per task and model like Immich's:
    # <cache>/embedding/bge-m3/. "/cache" (a volume) in the container.
    cache_path: Path = Field(default_factory=lambda: default_cache_path())
    # Shared secret: requests need "Authorization: Bearer <token>" when set.
    token: str | None = None
    # Unload a model after this many idle seconds (0: never).
    model_ttl: int = 300
    # Models to load at startup, never unloaded, e.g. ["bge-m3"].
    preload: list[str] = []
    # ONNX Runtime threads per model; 0 lets ONNX Runtime decide.
    intra_op_threads: int = 0
    # Most texts and tokens per inference batch (memory grows with both).
    max_batch_texts: int = 32
    max_batch_tokens: int = 16384


def default_cache_path() -> Path:
    """~/.cache/paperus-ml, or under $XDG_CACHE_HOME."""
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "paperus-ml"
