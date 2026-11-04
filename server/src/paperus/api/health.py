"""Health checks."""

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import OperationalError

from paperus.db import check_connection

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/db")
def health_db(request: Request) -> dict[str, str]:
    try:
        check_connection(request.app.state.engine)
    except OperationalError as error:
        raise HTTPException(503, "database unreachable") from error
    return {"status": "ok"}
