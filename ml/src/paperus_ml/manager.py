"""Loading models on first use, sharing them, and unloading idle ones."""

import logging
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from huggingface_hub import snapshot_download

from paperus_ml.config import Settings
from paperus_ml.encoder import Encoder
from paperus_ml.models import MODELS, ModelSpec

log = logging.getLogger(__name__)

Loader = Callable[[ModelSpec], Encoder]


class UnknownModel(KeyError):
    pass


class ModelManager:
    def __init__(self, settings: Settings, loader: Loader | None = None) -> None:
        self.settings = settings
        self._load = loader or self._download_and_load
        self._models: dict[str, tuple[Encoder, float]] = {}
        self._locks: dict[str, threading.Lock] = {
            name: threading.Lock() for name in MODELS
        }
        self._keep = set(settings.preload)
        self.threads = settings.intra_op_threads
        """CPU threads per model (0: all ONNX Runtime sees); set by paperus."""

    def model_dir(self, spec: ModelSpec) -> Path:
        """<cache>/<task>/<model>, with plain files: the shared Hugging Face
        cache uses symlinks, and ONNX Runtime refuses weight files that
        resolve outside the model's folder."""
        return self.settings.cache_path / spec.task / spec.name

    def cached_bytes(self, spec: ModelSpec) -> int | None:
        """Size on disk if the model is downloaded, else None."""
        directory = self.model_dir(spec)
        if not (directory / spec.onnx_file).is_file():
            return None
        return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())

    def delete_cached(self, name: str) -> None:
        """Unload a model and remove its files; it downloads again when used."""
        spec = MODELS.get(name)
        if spec is None:
            raise UnknownModel(name)
        with self._locks[name]:
            self._models.pop(name, None)
            shutil.rmtree(self.model_dir(spec), ignore_errors=True)

    def _download_and_load(self, spec: ModelSpec) -> Encoder:
        model_dir = self.model_dir(spec)
        # Revision changes download the changed files into the same folder.
        snapshot_download(
            spec.repo,
            revision=spec.revision,
            local_dir=model_dir,
            allow_patterns=[f"{spec.onnx_file}*", spec.tokenizer_file],
        )
        return Encoder(
            spec,
            model_dir,
            intra_op_threads=self.threads,
            max_batch_texts=self.settings.max_batch_texts,
            max_batch_tokens=self.settings.max_batch_tokens,
        )

    def get(self, name: str) -> Encoder:
        """The model, downloading and loading it on first use."""
        spec = MODELS.get(name)
        if spec is None:
            raise UnknownModel(name)
        with self._locks[name]:
            if name not in self._models:
                log.info("loading model %s", name)
                started = time.monotonic()
                encoder = self._load(spec)
                log.info("loaded %s in %.1f s", name, time.monotonic() - started)
            else:
                encoder = self._models[name][0]
            self._models[name] = (encoder, time.monotonic())
            return encoder

    def loaded(self) -> list[str]:
        return sorted(self._models)

    def unload_idle(self, now: float | None = None) -> list[str]:
        """Unload models idle longer than the TTL, except preloaded ones."""
        ttl = self.settings.model_ttl
        if ttl <= 0:
            return []
        now = time.monotonic() if now is None else now
        unloaded = []
        for name, (_, last_used) in list(self._models.items()):
            if name in self._keep or now - last_used < ttl:
                continue
            with self._locks[name]:
                self._models.pop(name, None)
            unloaded.append(name)
            log.info("unloaded idle model %s", name)
        return unloaded

    @property
    def kept(self) -> list[str]:
        return sorted(self._keep)

    def configure(self, *, threads: int, keep: list[str]) -> list[str]:
        """Settings from paperus' administration: threads per model, and the
        models to keep loaded (the one in use). Models loaded with other
        threads are unloaded; returns the models still to load (``load_kept``
        loads them, which can take a while)."""
        unknown = [name for name in keep if name not in MODELS]
        if unknown:
            raise UnknownModel(unknown[0])
        if threads != self.threads:
            self.threads = threads
            for name in list(self._models):
                with self._locks[name]:
                    self._models.pop(name, None)
        self._keep = set(keep)
        return [name for name in keep if name not in self._models]

    def load_kept(self) -> None:
        for name in self.kept:
            self.get(name)

    def preload(self) -> None:
        for name in self.settings.preload:
            self.get(name)
