"""Shared dependencies for API routes."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from paperus.auth import user_for_token
from paperus.models import User

SESSION_COOKIE = "paperus_session"


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as db:
        yield db


DB = Annotated[Session, Depends(get_db)]


def request_token(request: Request) -> str | None:
    """The session token from the cookie or an ``Authorization: Bearer`` header."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        return token
    return request.cookies.get(SESSION_COOKIE)


def current_user(request: Request, db: DB) -> User:
    token = request_token(request)
    user = user_for_token(db, token) if token else None
    if user is None:
        raise HTTPException(401, "not logged in")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
