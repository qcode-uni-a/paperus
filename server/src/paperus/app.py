"""FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI

from paperus.api import auth, health, items
from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker
from paperus.metadata import make_http_client


def create_app(
    settings: Settings | None = None, http_client: httpx2.Client | None = None
) -> FastAPI:
    """Build the app; tests pass their own ``http_client`` for external lookups."""
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    http = http_client or make_http_client(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        yield
        http.close()
        engine.dispose()

    app = FastAPI(title="paperUs", lifespan=lifespan)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.http = http
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(items.router)
    return app
