"""FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI
from procrastinate import App

from paperus.api import auth, files, health, items, search
from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker
from paperus.jobs import make_job_app
from paperus.metadata import make_http_client
from paperus.storage import make_blob_store


def create_app(
    settings: Settings | None = None,
    http_client: httpx2.Client | None = None,
    job_app: App | None = None,
) -> FastAPI:
    """Build the app; tests pass their own ``http_client`` and ``job_app``."""
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    http = http_client or make_http_client(settings)
    jobs = job_app or make_job_app(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        with jobs.open():
            yield
        http.close()
        engine.dispose()

    app = FastAPI(title="paperUs", lifespan=lifespan)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.http = http
    app.state.blobs = make_blob_store(settings)
    app.state.settings = settings
    app.state.jobs = jobs
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(items.router)
    app.include_router(files.router)
    app.include_router(search.router)
    return app
