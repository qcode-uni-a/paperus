"""FastAPI application."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from mcp.server.transport_security import TransportSecuritySettings
from procrastinate import App

from paperus import system, tokens
from paperus.access import Forbidden, NotVisible
from paperus.api import (
    admin,
    auth,
    backups,
    citations,
    duplicates,
    files,
    groups,
    health,
    imports,
    items,
    notes,
    organize,
    search,
    setup,
    trash,
    users,
)
from paperus.api import tokens as token_api
from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker
from paperus.jobs import make_job_app, queue_ml_configuration
from paperus.mcp_server import build_mcp
from paperus.metadata import make_http_client
from paperus.ml import MLClient, make_ml_client
from paperus.storage import make_blob_store
from paperus.web import FALLBACK, mount_web


def create_app(
    settings: Settings | None = None,
    http_client: httpx2.Client | None = None,
    job_app: App | None = None,
    ml_client: MLClient | None = None,
) -> FastAPI:
    """Build the app; tests pass their own clients and ``job_app``."""
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    http = http_client or make_http_client(settings)
    jobs = job_app or make_job_app(settings)
    ml = ml_client or make_ml_client(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # Log level and contact email as set in the administration.
        try:
            with app.state.sessionmaker() as db:
                system.apply(system.load_config(db, settings), http)
        except Exception:
            logging.getLogger(__name__).warning(
                "could not apply the saved settings", exc_info=True
            )
        with jobs.open():
            # The ML service starts from its own defaults; send ours.
            try:
                queue_ml_configuration(jobs)
            except Exception:
                logging.getLogger(__name__).warning(
                    "could not queue the ML configuration", exc_info=True
                )
            async with app.state.mcp.session_manager.run():
                yield
        http.close()
        ml.close()
        engine.dispose()

    app = FastAPI(
        title="paperus",
        lifespan=lifespan,
        # Operation IDs are the route functions' names, e.g. "get_item", so
        # generated clients get readable names.
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.http = http
    app.state.blobs = make_blob_store(settings)
    app.state.settings = settings
    app.state.jobs = jobs
    app.state.ml = ml
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(items.router)
    app.include_router(files.router)
    app.include_router(search.router)
    app.include_router(citations.router)
    app.include_router(notes.router)
    app.include_router(imports.router)
    app.include_router(duplicates.router)
    app.include_router(trash.router)
    app.include_router(admin.router)
    app.include_router(organize.router)
    app.include_router(groups.router)
    app.include_router(users.router)
    app.include_router(backups.router)
    app.include_router(setup.router)
    app.include_router(token_api.router)

    @app.exception_handler(Forbidden)
    def forbidden(request: Request, error: Forbidden) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=403)

    @app.exception_handler(NotVisible)
    def not_visible(request: Request, error: NotVisible) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=404)

    # The MCP server for AI assistants, before the website's catch-all.
    app.state.mcp = build_mcp(app.state)
    mcp_app = app.state.mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        # Only bearer tokens get in (never cookies), so DNS rebinding cannot
        # borrow a browser's login; behind any host name or proxy.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    app.router.routes.extend(mcp_app.routes)

    @app.middleware("http")
    async def mcp_needs_a_token(request: Request, call_next: Any) -> Response:  # noqa: ANN401
        """Clients learn at once that a token is missing or wrong."""
        if request.url.path == "/mcp":
            scheme, _, raw = request.headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not tokens.is_token(raw):
                return JSONResponse(
                    {"detail": "a paperus access token is needed"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        response: Response = await call_next(request)
        return response

    if settings.web_path is not None and (settings.web_path / FALLBACK).is_file():
        mount_web(app, settings.web_path)
    return app
