"""FastAPI application."""

from fastapi import FastAPI

from paperus.api import auth, health
from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    app = FastAPI(title="paperUs")
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.include_router(health.router)
    app.include_router(auth.router)
    return app
