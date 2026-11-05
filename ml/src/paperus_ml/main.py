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
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from paperus_ml.config import Settings
from paperus_ml.manager import ModelManager, UnknownModel
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
    threads: int = Field(ge=0, le=1024)
    """CPU threads per model; 0: all the service sees."""
    keep: list[str]
    """Models to keep loaded (paperus sends the one in use)."""


class ServiceState(ServiceConfig):
    cores: int
    """CPU cores this service may use."""
    loaded: list[str]


class Speed(BaseModel):
    model: str
    passages: int
    seconds: float
    passages_per_second: float
    load_seconds: float
    """Downloading and loading first, if the model was not loaded."""


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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        await asyncio.to_thread(models.preload)

        async def unload_loop() -> None:
            while True:
                await asyncio.sleep(UNLOAD_CHECK_SECONDS)
                models.unload_idle()

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
    def ping() -> str:
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
        passages) and time it: speed differs much between machines. Downloads
        and loads the model first if needed."""
        started = time.monotonic()
        try:
            encoder = models.get(name)
        except UnknownModel as error:
            raise HTTPException(404, f"unknown model {name!r}") from error
        load_seconds = time.monotonic() - started
        passages = sample_passages()
        encoder.embed(passages[:2], "passage")  # warm up
        started = time.monotonic()
        encoder.embed(passages, "passage")
        seconds = time.monotonic() - started
        return Speed(
            model=name,
            passages=len(passages),
            seconds=round(seconds, 2),
            passages_per_second=round(len(passages) / seconds, 1),
            load_seconds=round(load_seconds, 1),
        )

    @app.post("/embed", dependencies=[Depends(check_token)])
    def embed(body: EmbedRequest) -> EmbedResponse:
        """Runs in FastAPI's thread pool; ONNX Runtime releases the GIL."""
        try:
            encoder = models.get(body.model)
        except UnknownModel as error:
            raise HTTPException(404, f"unknown model {body.model!r}") from error
        vectors = encoder.embed(body.texts, body.kind)
        return EmbedResponse(
            model=body.model,
            dimensions=vectors.shape[1],
            embeddings=vectors.tolist(),
        )

    return app
