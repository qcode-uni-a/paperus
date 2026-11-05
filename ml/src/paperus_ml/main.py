"""HTTP API of paperus-ml.

``POST /embed`` with ``{"model": "bge-m3", "kind": "passage", "texts": [...]}``
returns one L2-normalized vector per text. The caller (paperus) names the
model in every request, so this service needs no model configuration.
"""

import asyncio
import contextlib
import os
import secrets
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from paperus_ml import metrics
from paperus_ml.config import Settings
from paperus_ml.encoder import Encoder
from paperus_ml.manager import ModelFailed, ModelLoading, ModelManager, UnknownModel
from paperus_ml.models import MODELS, SCORES, Kind
from paperus_ml.samples import sample_passages

MAX_TEXTS = 256
UNLOAD_CHECK_SECONDS = 30


class EmbedRequest(BaseModel):
    model: str
    kind: Kind = "passage"
    """Queries and passages get different prefixes in some models."""
    texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS)


class EmbedResponse(BaseModel):
    model: str
    dimensions: int
    embeddings: list[list[float]]


class ModelInfo(BaseModel):
    name: str
    task: str
    repo: str
    revision: str
    dimensions: int
    max_tokens: int
    loaded: bool
    cached_bytes: int | None
    """Size of the downloaded files; None if not downloaded yet."""
    description: str
    licence: str
    download_mb: int
    scores: dict[str, float]
    """Published retrieval scores (nDCG@10, out of 100) by benchmark."""
    benchmarks: dict[str, str] = Field(default_factory=lambda: dict(SCORES))
    """What the score keys mean."""


class ServiceConfig(BaseModel):
    threads: int | None = Field(default=None, ge=0, le=1024)
    """CPU threads per model; 0: all the service sees; None: its own
    setting (``PAPERUS_ML_INTRA_OP_THREADS``)."""
    keep: list[str]
    """Models to keep loaded (paperus sends the one in use)."""


class ServiceState(BaseModel):
    threads: int
    keep: list[str]
    cores: int
    """CPU cores this service may use."""
    loaded: list[str]
    loading: list[str]
    started: str
    """When this service started (an ID: a new value means a restart)."""


class Speed(BaseModel):
    model: str
    passages: int
    seconds: float
    passages_per_second: float


def usable_cores() -> int:
    """Cores this process may run on (a container's CPU set, if limited)."""
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:  # not on Linux
        return os.cpu_count() or 1


def create_app(
    settings: Settings | None = None, manager: ModelManager | None = None
) -> FastAPI:
    settings = settings or Settings()
    models = manager or ModelManager(settings)
    started = datetime.now(UTC).isoformat()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        if settings.metrics_port:
            metrics.serve(
                settings.metrics_port,
                metrics.ModelsCollector(models.loaded, models.loading),
            )
        await asyncio.to_thread(models.preload)

        async def unload_loop() -> None:
            while True:
                await asyncio.sleep(UNLOAD_CHECK_SECONDS)
                await asyncio.to_thread(models.unload_idle)

        task = asyncio.create_task(unload_loop())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def check_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if settings.token is None:
            return
        scheme, _, token = (authorization or "").partition(" ")
        valid = scheme.lower() == "bearer" and secrets.compare_digest(
            token.encode(), settings.token.encode()
        )
        if not valid:
            raise HTTPException(401, "token required")

    app = FastAPI(
        title="paperus-ml",
        lifespan=lifespan,
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.models = models

    @app.get("/ping")
    async def ping() -> str:
        # Async: answers even when every worker thread is busy.
        return "pong"

    @app.get("/models", dependencies=[Depends(check_token)])
    def list_models() -> list[ModelInfo]:
        loaded = set(models.loaded())
        return [
            ModelInfo(
                name=s.name,
                task=s.task,
                repo=s.repo,
                revision=s.revision,
                dimensions=s.dimensions,
                max_tokens=s.max_tokens,
                loaded=s.name in loaded,
                cached_bytes=models.cached_bytes(s),
                description=s.description,
                licence=s.licence,
                download_mb=s.download_mb,
                scores=dict(s.scores),
            )
            for s in MODELS.values()
        ]

    @app.delete("/models/{name}", status_code=204, dependencies=[Depends(check_token)])
    def delete_model(name: str) -> None:
        """Remove a downloaded model to free disk space."""
        try:
            models.delete_cached(name)
        except UnknownModel as error:
            raise HTTPException(404, f"unknown model {name!r}") from error

    @app.get("/config", dependencies=[Depends(check_token)])
    def get_config() -> ServiceState:
        return ServiceState(
            threads=models.threads,
            keep=models.kept,
            cores=usable_cores(),
            loaded=models.loaded(),
            loading=models.loading(),
            started=started,
        )

    @app.put("/config", dependencies=[Depends(check_token)])
    def set_config(body: ServiceConfig, tasks: BackgroundTasks) -> ServiceState:
        """Apply paperus' settings; kept models load in the background."""
        try:
            missing = models.configure(threads=body.threads, keep=body.keep)
        except UnknownModel as error:
            raise HTTPException(404, f"unknown model {error.args[0]!r}") from error
        if missing:
            tasks.add_task(models.load_kept)
        return get_config()

    @app.post("/models/{name}/speed", dependencies=[Depends(check_token)])
    def measure_speed(name: str) -> Speed:
        """Embed sample passages (about 250 words each, like paperus'
        passages) and time it: speed differs much between machines. A model
        not loaded yet starts loading and the answer is 503 "loading": ask
        again. Other requests for the model wait while it measures, so they
        do not slow the measurement (other models still can)."""
        encoder = _model(name)
        passages = sample_passages()
        with encoder.running:
            encoder.embed(passages[:2], "passage")  # warm up
            started = time.monotonic()
            encoder.embed(passages, "passage")
            seconds = time.monotonic() - started
        return Speed(
            model=name,
            passages=len(passages),
            seconds=round(seconds, 2),
            passages_per_second=round(len(passages) / max(seconds, 1e-6), 1),
        )

    def _model(name: str) -> Encoder:
        try:
            return models.get(name, wait=settings.load_wait)
        except UnknownModel as error:
            raise HTTPException(404, f"unknown model {name!r}") from error
        except ModelLoading as error:
            raise HTTPException(
                503, f"model {name!r} is loading", headers={"Retry-After": "10"}
            ) from error
        except ModelFailed as error:
            raise HTTPException(
                502, f"loading model {name!r} failed: {error.args[1]}"
            ) from error

    @app.post("/embed", dependencies=[Depends(check_token)])
    def embed(body: EmbedRequest) -> EmbedResponse:
        """Runs in FastAPI's thread pool; ONNX Runtime releases the GIL."""
        try:
            vectors = _model(body.model).embed(body.texts, body.kind)
        except HTTPException as error:
            outcome = "loading" if error.status_code == 503 else "error"
            metrics.REQUESTS.labels(body.model, body.kind, outcome).inc()
            raise
        metrics.REQUESTS.labels(body.model, body.kind, "ok").inc()
        metrics.TEXTS.labels(body.model, body.kind).inc(len(body.texts))
        return EmbedResponse(
            model=body.model,
            dimensions=vectors.shape[1],
            embeddings=vectors.tolist(),
        )

    return app
