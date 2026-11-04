"""Loading models on first use, sharing them, and unloading idle ones."""

import logging
import threading
import time
from collections.abc import Callable

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

    def _download_and_load(self, spec: ModelSpec) -> Encoder:
        # Plain files in a folder per model and revision: the shared Hugging
        # Face cache uses symlinks, and ONNX Runtime refuses weight files
        # that resolve outside the model's folder.
        model_dir = self.settings.cache_path / spec.name / spec.revision
        snapshot_download(
            spec.repo,
            revision=spec.revision,
            local_dir=model_dir,
            allow_patterns=[f"{spec.onnx_file}*", spec.tokenizer_file],
        )
        return Encoder(
            spec,
            model_dir,
            intra_op_threads=self.settings.intra_op_threads,
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

    def preload(self) -> None:
        for name in self.settings.preload:
            self.get(name)
