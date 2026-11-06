"""Loading models on first use, sharing them, and unloading idle ones."""

import logging
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from huggingface_hub import snapshot_download

from paperus_ml.config import Settings
from paperus_ml.device import Device, choose
from paperus_ml.encoder import Encoder
from paperus_ml.models import MODELS, ModelSpec

log = logging.getLogger(__name__)

Loader = Callable[[ModelSpec], Encoder]


class UnknownModel(KeyError):
    pass


class ModelLoading(Exception):
    """The model is still downloading or loading; ask again shortly."""


class ModelFailed(Exception):
    """Loading the model failed (e.g. the download); the message says why."""


class ModelManager:
    def __init__(self, settings: Settings, loader: Loader | None = None) -> None:
        self.settings = settings
        self._load = loader or self._download_and_load
        # name → (encoder, last used, threads it was loaded with)
        self._models: dict[str, tuple[Encoder, float, int]] = {}
        self._loading: dict[str, threading.Event] = {}
        self._errors: dict[str, str] = {}
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {
            name: threading.Lock() for name in MODELS
        }
        self._keep = set(settings.preload)
        self.threads = settings.intra_op_threads
        """CPU threads per model (0: all ONNX Runtime sees); set by paperus."""
        self.device: Device = choose(settings.device)
        """Where models run (each model loads the file for it)."""

    def model_dir(self, spec: ModelSpec) -> Path:
        """<cache>/<task>/<model>, with plain files: the shared Hugging Face
        cache uses symlinks, and ONNX Runtime refuses weight files that
        resolve outside the model's folder."""
        return self.settings.cache_path / spec.task / spec.name

    def cached_bytes(self, spec: ModelSpec) -> int | None:
        """Size on disk if the model is downloaded, else None."""
        directory = self.model_dir(spec)
        if not (directory / spec.onnx_file_for(self.device)).is_file():
            return None
        return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())

    def delete_cached(self, name: str) -> None:
        """Unload a model and remove its files; it downloads again when used."""
        spec = MODELS.get(name)
        if spec is None:
            raise UnknownModel(name)
        with self._locks[name]:
            self._models.pop(name, None)
            self._errors.pop(name, None)
            shutil.rmtree(self.model_dir(spec), ignore_errors=True)

    def _download_and_load(self, spec: ModelSpec) -> Encoder:
        model_dir = self.model_dir(spec)
        # Revision changes download the changed files into the same folder.
        snapshot_download(
            spec.repo,
            revision=spec.revision,
            local_dir=model_dir,
            allow_patterns=[f"{spec.onnx_file_for(self.device)}*", spec.tokenizer_file],
        )
        encoder = Encoder(
            spec,
            model_dir,
            intra_op_threads=self.threads,
            max_batch_texts=self.settings.max_batch_texts,
            max_batch_tokens=self.settings.max_batch_tokens,
            device=self.device,
        )
        if encoder.device != self.device:
            log.warning("%s: no usable GPU, running on the CPU", spec.name)
        return encoder

    def get(self, name: str, wait: float | None = None) -> Encoder:
        """The model, downloading and loading it on first use (and again when
        the threads changed). ``wait=None`` blocks until it is ready; with
        ``wait`` in seconds, loading continues in the background and
        ``ModelLoading`` is raised if it takes longer, so requests do not pile
        up behind a download."""
        spec = MODELS.get(name)
        if spec is None:
            raise UnknownModel(name)
        ready = self._ready(name)
        if ready is not None:
            return ready
        if wait is None:
            return self._load_now(name, spec)
        done = self._load_in_background(name)
        done.wait(wait)
        ready = self._ready(name)
        if ready is not None:
            return ready
        if name in self._errors and not self._loading_now(name):
            raise ModelFailed(name, self._errors[name])
        raise ModelLoading(name)

    def _ready(self, name: str) -> Encoder | None:
        """The loaded model, if loaded with the current threads."""
        entry = self._models.get(name)
        if entry is None or entry[2] != self.threads:
            return None
        self._models[name] = (entry[0], time.monotonic(), entry[2])
        return entry[0]

    def _load_now(self, name: str, spec: ModelSpec) -> Encoder:
        with self._locks[name]:
            ready = self._ready(name)
            if ready is not None:
                return ready
            # Drop an old copy (other threads) before loading the new one.
            self._models.pop(name, None)
            threads = self.threads
            log.info("loading model %s", name)
            started = time.monotonic()
            try:
                encoder = self._load(spec)
            except Exception as error:
                self._errors[name] = str(error) or type(error).__name__
                raise
            self._errors.pop(name, None)
            log.info("loaded %s in %.1f s", name, time.monotonic() - started)
            self._models[name] = (encoder, time.monotonic(), threads)
            return encoder

    def _load_in_background(self, name: str) -> threading.Event:
        with self._guard:
            if name in self._loading:
                return self._loading[name]
            done = threading.Event()
            self._loading[name] = done

        def load() -> None:
            try:
                self.get(name)
            except Exception:
                log.warning("loading %s failed", name, exc_info=True)
            finally:
                with self._guard:
                    self._loading.pop(name, None)
                done.set()

        threading.Thread(target=load, name=f"load-{name}", daemon=True).start()
        return done

    def _loading_now(self, name: str) -> bool:
        with self._guard:
            return name in self._loading

    def loading(self) -> list[str]:
        with self._guard:
            return sorted(self._loading)

    def loaded(self) -> list[str]:
        return sorted(self._models)

    def unload_idle(self, now: float | None = None) -> list[str]:
        """Unload models idle longer than the TTL, except kept ones. Skips a
        model that is busy loading; checks again under its lock."""
        ttl = self.settings.model_ttl
        if ttl <= 0:
            return []
        now = time.monotonic() if now is None else now
        unloaded = []
        for name in list(self._models):
            lock = self._locks[name]
            if not lock.acquire(blocking=False):
                continue
            try:
                entry = self._models.get(name)
                if entry is None or name in self._keep or now - entry[1] < ttl:
                    continue
                self._models.pop(name, None)
            finally:
                lock.release()
            unloaded.append(name)
            log.info("unloaded idle model %s", name)
        return unloaded

    @property
    def kept(self) -> list[str]:
        return sorted(self._keep)

    def configure(self, *, threads: int | None, keep: list[str]) -> list[str]:
        """Settings from paperus' administration: threads per model (None:
        this service's own setting), and the models to keep loaded (the one
        in use). Models loaded with other threads load again when next used
        (requests running keep theirs). Returns the kept models still to load
        (``load_kept`` loads them, which can take a while)."""
        unknown = [name for name in keep if name not in MODELS]
        if unknown:
            raise UnknownModel(unknown[0])
        self.threads = self.settings.intra_op_threads if threads is None else threads
        self._keep = set(keep)
        return [name for name in keep if self._ready(name) is None]

    def load_kept(self) -> None:
        for name in self.kept:
            self.get(name)

    def preload(self) -> None:
        for name in self.settings.preload:
            self.get(name)
