"""Shared dependencies for API routes."""

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from paperus import tokens
from paperus.access import Access
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
    """The logged-in person, by session or by access token (which may only
    make the calls its scopes allow, see ``paperus.tokens``)."""
    raw = request_token(request)
    request.state.access_token = None
    if raw and tokens.is_token(raw):
        found = tokens.find_token(db, raw)
        if found is None:
            raise HTTPException(401, "invalid or expired token")
        token, user = found
        if not tokens.allows(token, request.method, request.url.path):
            raise HTTPException(403, "this token may not do that")
        request.state.access_token = token
        return user
    user = user_for_token(db, raw) if raw else None
    if user is None:
        raise HTTPException(401, "not logged in")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def current_access(request: Request, user: CurrentUser, db: DB) -> Access:
    """What the person may read and change (see ``paperus.access``),
    narrowed to an access token's owners if it has a limit."""
    token = getattr(request.state, "access_token", None)
    # Who acts, for notifications (papers given to a group: by whom).
    db.info["paperus_actor"] = user.id
    only = None
    if token is not None and token.library_ids is not None:
        only = [uuid.UUID(i) for i in token.library_ids]
    return Access.of(db, user, only, token=token is not None)


def session_user(request: Request, user: CurrentUser) -> User:
    """Only logged-in people, not access tokens (account management)."""
    if getattr(request.state, "access_token", None) is not None:
        raise HTTPException(403, "not with an access token")
    return user


SessionUser = Annotated[User, Depends(session_user)]


CurrentAccess = Annotated[Access, Depends(current_access)]
