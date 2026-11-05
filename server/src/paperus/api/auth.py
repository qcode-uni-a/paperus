"""Login, logout and the current user."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from paperus import auth
from paperus.api.deps import DB, SESSION_COOKIE, CurrentUser, request_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    is_admin: bool


class PasswordChange(BaseModel):
    current: str
    new: Annotated[str, Field(min_length=8, max_length=200)]


class LoginResponse(BaseModel):
    token: str
    user: UserOut


def user_out(user: auth.User) -> UserOut:
    return UserOut(id=user.id, username=user.username, is_admin=user.is_admin)


@router.post("/login")
def login(
    body: LoginRequest, request: Request, response: Response, db: DB
) -> LoginResponse:
    user = auth.authenticate(db, body.username, body.password)
    if user is None:
        raise HTTPException(401, "wrong username or password")
    token = auth.start_session(db, user)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(auth.SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
    )
    return LoginResponse(token=token, user=user_out(user))


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DB) -> None:
    token = request_token(request)
    if token:
        auth.end_session(db, token)
        db.commit()
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return user_out(user)


@router.post("/password", status_code=204)
def change_password(
    body: PasswordChange, request: Request, db: DB, user: CurrentUser
) -> None:
    """Change one's password (the current one is needed); other devices are
    logged out, this one stays logged in."""
    if not auth.verify_password(user.password_hash, body.current):
        raise HTTPException(403, "the current password is wrong")
    auth.change_password(db, user, body.new, keep_token=request_token(request) or "")
    db.commit()
