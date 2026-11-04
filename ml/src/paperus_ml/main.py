"""HTTP API of paperus-ml.

``POST /embed`` with ``{"model": "bge-m3", "kind": "passage", "texts": [...]}``
returns one L2-normalized vector per text. The caller (paperus) names the
model in every request, so this service needs no model configuration.
"""

import asyncio
import contextlib
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from paperus_ml.config import Settings
from paperus_ml.manager import ModelManager, UnknownModel
from paperus_ml.models import MODELS, Kind

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
    repo: str
    revision: str
    dimensions: int
    max_tokens: int
    loaded: bool


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
                repo=s.repo,
                revision=s.revision,
                dimensions=s.dimensions,
                max_tokens=s.max_tokens,
                loaded=s.name in loaded,
            )
            for s in MODELS.values()
        ]

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
