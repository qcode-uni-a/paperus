"""FastAPI application."""

from fastapi import FastAPI, HTTPException
from sqlalchemy.exc import OperationalError

from paperus.config import Settings
from paperus.db import check_connection, make_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    app = FastAPI(title="paperUs")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health/db")
    def health_db() -> dict[str, str]:
        try:
            check_connection(engine)
        except OperationalError as error:
            raise HTTPException(503, "database unreachable") from error
        return {"status": "ok"}

    return app
