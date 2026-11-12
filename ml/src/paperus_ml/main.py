"""HTTP API of paperus-ml.

``POST /embed`` with ``{"model": "bge-m3", "kind": "passage", "texts": [...]}``
returns one L2-normalized vector per text; ``POST /rerank`` scores passages
for a query; ``POST /ocr/{model}`` with an image reads its text. The caller
(paperus) names the model in every request, so this service needs no model
configuration.
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

import onnxruntime
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from paperus_ml import memory, metrics
from paperus_ml.config import Settings
from paperus_ml.device import CUDA, DRIVER_NEEDED, driver_version, host_cards
from paperus_ml.encoder import Encoder
from paperus_ml.manager import (
    Model,
    ModelFailed,
    ModelLoading,
    ModelManager,
    UnknownModel,
)
from paperus_ml.models import MODELS, SCORES, Kind
from paperus_ml.ocr import NotAnImage, Reader
from paperus_ml.rerank import Reranker
from paperus_ml.samples import sample_page, sample_passages

MAX_TEXTS = 256
MAX_IMAGE_BYTES = 64 * 1024 * 1024
UNLOAD_CHECK_SECONDS = 30
OCR_SPEED_PAGES = 3


class EmbedRequest(BaseModel):
    model: str
    kind: Kind = "passage"
    """Queries and passages get different prefixes in some models."""
    texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS)


class EmbedResponse(BaseModel):
    model: str
    vectors: str
    """What to store the vectors as: the model's name, with the variant of
    its file when not the usual one (``…@fp16`` on a GPU); vectors of
    different variants must not be mixed."""
    dimensions: int
    embeddings: list[list[float]]


class RerankRequest(BaseModel):
    model: str
    query: str = Field(min_length=1, max_length=2000)
    passages: list[str] = Field(min_length=1, max_length=200)


class RerankResponse(BaseModel):
    model: str
    scores: list[float]
    """One per passage, in their order: higher fits better (only the order
    means something)."""


class OcrLine(BaseModel):
    text: str
    score: float
    """How sure the model is (0 to 1)."""
    box: tuple[int, int, int, int]
    """Left, top, right, bottom in pixels of the image."""


class OcrResponse(BaseModel):
    model: str
    text: str
    """The page's text in reading order (columns one after the other); a
    blank line between blocks."""
    lines: list[OcrLine]
    width: int
    height: int


class ModelInfo(BaseModel):
    name: str
    task: str
    repo: str
    revision: str
    dimensions: int
    max_tokens: int
    vectors: str
    """What its vectors are stored as on this service (see EmbedResponse)."""
    loaded: bool
    cached_bytes: int | None
    """Size of the downloaded files; None if not downloaded yet."""
    description: str
    licence: str
    download_mb: int
    scores: dict[str, float]
    """Published retrieval scores (nDCG@10, out of 100) by benchmark."""
    memory_bytes: int | None = None
    """What it took once loaded on this service (RAM, or GPU memory on the
    GPU), as measured when it last loaded; None if never loaded here. Runs
    need some more for a moment."""
    benchmarks: dict[str, str] = Field(default_factory=lambda: dict(SCORES))
    """What the score keys mean."""


class ServiceConfig(BaseModel):
    threads: int | None = Field(default=None, ge=0, le=1024)
    """CPU threads per model; 0: all the service sees; None: its own
    setting (``PAPERUS_ML_INTRA_OP_THREADS``)."""
    keep: list[str]
    """Models to keep loaded (paperus sends the one in use)."""


class MemoryOut(BaseModel):
    total: int
    free: int
    """Bytes; free: available for new use."""


class GPU(BaseModel):
    name: str
    supported: bool
    """New enough for the GPU image (RTX 20xx generation or newer)."""


class ServiceState(BaseModel):
    threads: int
    keep: list[str]
    cores: int
    """CPU cores this service may use."""
    device: str = "cpu"
    """Where models run: "cpu", or "cuda" (an NVIDIA GPU)."""
    loaded: list[str]
    loading: list[str]
    started: str
    """When this service started (an ID: a new value means a restart)."""
    cuda_image: bool = False
    """The GPU image (ONNX Runtime with CUDA)."""
    gpu_problem: str | None = None
    """Why models run on the CPU (None on the GPU)."""
    gpus: list[GPU] = []
    """The machine's NVIDIA cards, also those not passed to this container."""
    driver: int | None = None
    """The NVIDIA driver's major version, if one is loaded."""
    driver_needed: int = DRIVER_NEEDED
    """The oldest driver the GPU image runs with."""
    ram: MemoryOut | None = None
    """The machine's RAM, if the system says."""
    gpu_memory: MemoryOut | None = None
    """The GPU's memory (all programs' use counted), on the GPU."""
    on_cpu: dict[str, str] = Field(default_factory=dict)
    """Models running on the CPU although the service runs on the GPU,
    with why (not enough GPU memory)."""


class Speed(BaseModel):
    model: str
    passages: int
    seconds: float
    passages_per_second: float


def _memory(found: memory.Memory | None) -> MemoryOut | None:
    return None if found is None else MemoryOut(total=found.total, free=found.free)


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
                vectors=s.vectors(models.device),
                loaded=s.name in loaded,
                cached_bytes=models.cached_bytes(s),
                description=s.description,
                licence=s.licence,
                download_mb=s.download_mb,
                scores=dict(s.scores),
                memory_bytes=models.measured.get(s.vectors(models.device)),
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
            device=models.device,
            loaded=models.loaded(),
            loading=models.loading(),
            started=started,
            cuda_image=CUDA in onnxruntime.get_available_providers(),
            gpu_problem=models.gpu_problem,
            gpus=[GPU(name=c.name, supported=c.supported) for c in host_cards()],
            driver=driver_version(),
            ram=_memory(memory.ram()),
            gpu_memory=_memory(memory.gpu()) if models.device == "cuda" else None,
            on_cpu=dict(models.on_cpu),
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
        model = _load(name)
        passages = sample_passages()
        with model.running:
            if isinstance(model, Reader):
                # Pages instead of passages.
                page = sample_page()
                model.read(page)
                started = time.monotonic()
                for _ in range(OCR_SPEED_PAGES):
                    model.read(page)
                seconds = time.monotonic() - started
                return Speed(
                    model=name,
                    passages=OCR_SPEED_PAGES,
                    seconds=round(seconds, 2),
                    passages_per_second=round(OCR_SPEED_PAGES / max(seconds, 1e-6), 2),
                )
            if isinstance(model, Reranker):
                # Search hits: one query against all passages.
                model.score("what did the measurements show", passages[:2])
                started = time.monotonic()
                model.score("what did the measurements show", passages)
            else:
                model.embed(passages[:2], "passage")  # warm up
                started = time.monotonic()
                model.embed(passages, "passage")
            seconds = time.monotonic() - started
        return Speed(
            model=name,
            passages=len(passages),
            seconds=round(seconds, 2),
            passages_per_second=round(len(passages) / max(seconds, 1e-6), 1),
        )

    def _load(name: str) -> Model:
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

    def _model[M: Model](name: str, kind: str, task: type[M], what: str) -> M:
        """The model for a request, of the task it needs; failed requests
        are counted (as "loading" while it loads)."""
        try:
            model = _load(name)
            if not isinstance(model, task):
                raise HTTPException(422, f"{name!r} is not {what}")
        except HTTPException as error:
            outcome = "loading" if error.status_code == 503 else "error"
            metrics.REQUESTS.labels(name, kind, outcome).inc()
            raise
        return model

    @app.post("/embed", dependencies=[Depends(check_token)])
    def embed(body: EmbedRequest) -> EmbedResponse:
        """Runs in FastAPI's thread pool; ONNX Runtime releases the GIL."""
        model = _model(body.model, body.kind, Encoder, "an embedding model")
        vectors = model.embed(body.texts, body.kind)
        metrics.REQUESTS.labels(body.model, body.kind, "ok").inc()
        metrics.TEXTS.labels(body.model, body.kind).inc(len(body.texts))
        return EmbedResponse(
            model=body.model,
            vectors=MODELS[body.model].vectors(models.device),
            dimensions=vectors.shape[1],
            embeddings=vectors.tolist(),
        )

    @app.post("/rerank", dependencies=[Depends(check_token)])
    def rerank(body: RerankRequest) -> RerankResponse:
        """Score how well each passage answers the query, for reordering
        search hits. Runs in FastAPI's thread pool, like /embed."""
        model = _model(body.model, "rerank", Reranker, "a reranker")
        scores = model.score(body.query, body.passages)
        metrics.REQUESTS.labels(body.model, "rerank", "ok").inc()
        metrics.TEXTS.labels(body.model, "rerank").inc(len(body.passages))
        return RerankResponse(model=body.model, scores=scores)

    @app.post("/ocr/{name}", dependencies=[Depends(check_token)])
    async def ocr(name: str, request: Request) -> OcrResponse:
        """The text in the image sent as the request's body (PNG, JPEG,
        TIFF, WebP; a page at 200-300 dpi reads best). One page per
        request; a few seconds each on a CPU."""
        data = await request.body()
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413 if data else 422, "send one image of up to 64 MB")
        model = await asyncio.to_thread(
            lambda: _model(name, "ocr", Reader, "an OCR model")
        )
        try:
            page = await asyncio.to_thread(model.read, data)
        except NotAnImage as error:
            raise HTTPException(422, str(error)) from error
        metrics.REQUESTS.labels(name, "ocr", "ok").inc()
        metrics.TEXTS.labels(name, "ocr").inc()
        return OcrResponse(
            model=name,
            text=page.text,
            lines=[
                OcrLine(text=line.text, score=round(line.score, 3), box=line.box)
                for line in page.lines
            ],
            width=page.width,
            height=page.height,
        )

    return app
