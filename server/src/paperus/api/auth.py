"""Login, logout and the current user."""

import json
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Path, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import auth, authors, automations, oidc
from paperus.api.deps import (
    DB,
    SESSION_COOKIE,
    CurrentUser,
    SessionUser,
    request_token,
)
from paperus.avatars import avatar_url
from paperus.jobs import queue_own_papers
from paperus.models import Author, Library
from paperus.system import DateFormat, SystemConfig, load_config, oidc_secret

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


NameFormat = Literal["family-given", "given-family"]


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str | None = None
    """Shown to others instead of the username, if set."""
    orcid: str | None = None
    """Their own ORCID iD (only they see it)."""
    author_id: uuid.UUID | None = None
    """The author with that iD, if one is known: them."""
    is_admin: bool
    seen_hints: list[str]
    """Tutorial hints already shown to the person."""
    oidc_linked: bool = False
    """The account is linked to the OIDC login."""
    avatar_url: str | None = None
    """The profile picture, if one is set."""
    date_format: DateFormat = "browser"
    """How dates and times are shown (the installation's setting)."""
    handed_over: "HandedOver | None" = None
    """While the account was deactivated, its library went to someone else."""
    name_format: NameFormat = "family-given"
    """How the website writes people's names (the person's choice)."""


class HandedOver(BaseModel):
    at: datetime
    to: str
    """A person's username, or "the group …"."""
    by: str
    """The administrator."""
    papers: int


class PasswordChange(BaseModel):
    current: str
    new: Annotated[str, Field(min_length=8, max_length=200)]


class LoginResponse(BaseModel):
    token: str
    user: UserOut


def user_out(
    user: auth.User, date_format: DateFormat, author_id: uuid.UUID | None = None
) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        orcid=user.orcid,
        author_id=author_id,
        is_admin=user.is_admin,
        seen_hints=user.seen_hints,
        oidc_linked=user.oidc_subject is not None,
        avatar_url=avatar_url(user.id, user.avatar_version),
        date_format=date_format,
        handed_over=HandedOver(**user.handed_over) if user.handed_over else None,
        name_format=user.name_format,  # ty: ignore[invalid-argument-type]
    )


def session_user_out(user: auth.User, db: Session, request: Request) -> UserOut:
    """The person as the website keeps them, with the installation's date
    format and the author they are."""
    author_id = (
        db.scalar(select(Author.id).where(Author.orcid == user.orcid))
        if user.orcid
        else None
    )
    date_format = load_config(db, request.app.state.settings).date_format
    return user_out(user, date_format, author_id)


@router.post("/login")
def login(
    body: LoginRequest, request: Request, response: Response, db: DB
) -> LoginResponse:
    user = auth.authenticate(db, body.username, body.password)
    if user is None:
        raise HTTPException(401, "wrong username or password")
    config = load_config(db, request.app.state.settings)
    if not config.password_login and not user.is_admin:
        db.rollback()
        raise HTTPException(403, f"log in with {config.oidc_label}")
    token = auth.start_session(db, user, timedelta(days=config.session_days))
    db.commit()
    set_session_cookie(request, response, token, config.session_days)
    return LoginResponse(token=token, user=session_user_out(user, db, request))


def set_session_cookie(
    request: Request, response: Response, token: str, days: int
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=days * 24 * 3600,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
    )


def check_password_length(db: Session, request: Request, password: str) -> None:
    """At least as long as the administration asks (Authentication)."""
    least = load_config(db, request.app.state.settings).password_min_length
    if len(password) < least:
        raise HTTPException(422, f"the password needs at least {least} characters")


class LoginMethods(BaseModel):
    password: bool
    """Everyone may log in with a password (else only administrators)."""
    oidc_label: str | None
    """The OIDC login's button, if it is on."""


@router.get("/methods")
def login_methods(request: Request, db: DB) -> LoginMethods:
    """How one may log in (for the login page)."""
    config = load_config(db, request.app.state.settings)
    return LoginMethods(
        password=config.password_login,
        oidc_label=config.oidc_label if config.oidc_enabled else None,
    )


OIDC_COOKIE = "paperus_oidc"
OIDC_CALLBACK = "/api/auth/oidc/callback"


def public_base(request: Request, config: SystemConfig) -> str:
    """The address people use: the one set in the administration, else the
    one this request came to."""
    if config.public_url:
        return str(config.public_url).rstrip("/")
    return str(request.base_url).rstrip("/")


def _session_user(request: Request, db: Session) -> auth.User | None:
    """Who is logged in with the session cookie (not a token)."""
    token = request.cookies.get(SESSION_COOKIE)
    return auth.user_for_token(db, token) if token else None


def _failed(
    request: Request, config: SystemConfig, back: str, link: bool, error: str
) -> RedirectResponse:
    """To the login page, or (when linking) back where one came from."""
    if link:
        separator = "&" if "?" in back else "?"
        target = f"{back}{separator}link_error={quote(error)}"
    else:
        target = f"/login?error={quote(error)}"
    response = RedirectResponse(public_base(request, config) + target, status_code=303)
    response.delete_cookie(OIDC_COOKIE, path="/api/auth/oidc")
    return response


def _login_page(request: Request, config: SystemConfig, error: str) -> RedirectResponse:
    return _failed(request, config, "/", False, error)


@router.get("/oidc/start")
def oidc_start(
    request: Request, db: DB, next: str = "/", link: bool = False
) -> RedirectResponse:
    """Off to the identity provider; it sends the browser back to
    ``/api/auth/oidc/callback``. With ``link``, the OIDC login is
    linked to the account logged in now instead (whatever its name)."""
    config = load_config(db, request.app.state.settings)
    # Only paths of this site, so the login cannot send one elsewhere.
    back = next if next.startswith("/") and not next.startswith("//") else "/"
    if link and _session_user(request, db) is None:
        return _login_page(request, config, "Log in first to link your account.")
    if not config.oidc_enabled or not config.oidc_issuer or not config.oidc_client_id:
        return _failed(request, config, back, link, "The OIDC login is off.")
    try:
        provider = oidc.discover(request.app.state.http, config.oidc_issuer)
    except oidc.LoginFailed as error:
        return _failed(request, config, back, link, f"OIDC login failed: {error}.")
    redirect_uri = public_base(request, config) + OIDC_CALLBACK
    started = oidc.start(provider, config.oidc_client_id, redirect_uri)
    response = RedirectResponse(started.url, status_code=303)
    response.set_cookie(
        OIDC_COOKIE,
        json.dumps([started.state, started.nonce, started.verifier, back, link]),
        max_age=600,
        path="/api/auth/oidc",
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/oidc/callback")
def oidc_callback(
    request: Request,
    db: DB,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """Back from the identity provider: log the person in."""
    settings = request.app.state.settings
    config = load_config(db, settings)
    try:
        saved_state, nonce, verifier, back, link = json.loads(
            request.cookies.get(OIDC_COOKIE, "")
        )
    except (ValueError, TypeError):
        return _login_page(request, config, "The login took too long; try again.")
    if error:
        reason = f"OIDC login failed: {error_description or error}."
        return _failed(request, config, back, link, reason)
    if not code or not state or state != saved_state:
        reason = "The login was not started here; try again."
        return _failed(request, config, back, link, reason)
    if not config.oidc_enabled or not config.oidc_issuer or not config.oidc_client_id:
        return _failed(request, config, back, link, "The OIDC login is off.")
    try:
        provider = oidc.discover(request.app.state.http, config.oidc_issuer)
        claims = oidc.finish(
            request.app.state.http,
            provider,
            client_id=config.oidc_client_id,
            client_secret=oidc_secret(db, settings),
            redirect_uri=public_base(request, config) + OIDC_CALLBACK,
            code=code,
            verifier=verifier,
            nonce=nonce,
        )
        if link:
            current = _session_user(request, db)
            if current is None:
                raise oidc.LoginFailed("you were logged out meanwhile")
            oidc.link(db, current, claims)
            oidc.take_picture(request.app.state.http, current, claims, provider.issuer)
        else:
            user, linked = oidc.user_for(db, claims, config)
            if linked:
                oidc.take_picture(request.app.state.http, user, claims, provider.issuer)
    except oidc.LoginFailed as failure:
        db.rollback()
        reason = f"OIDC login failed: {failure}."
        return _failed(request, config, back, link, reason)
    response = RedirectResponse(public_base(request, config) + back, status_code=303)
    response.delete_cookie(OIDC_COOKIE, path="/api/auth/oidc")
    if not link:
        token = auth.start_session(db, user, timedelta(days=config.session_days))
        set_session_cookie(request, response, token, config.session_days)
    db.commit()
    return response


@router.delete("/oidc/link", status_code=204)
def unlink_oidc(db: DB, user: SessionUser) -> None:
    """Unlink one's account from the OIDC login (the password stays)."""
    user.oidc_subject = None
    db.commit()


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DB) -> None:
    token = request_token(request)
    if token:
        auth.end_session(db, token)
        db.commit()
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me")
def me(user: CurrentUser, db: DB, request: Request) -> UserOut:
    return session_user_out(user, db, request)


@router.post("/password", status_code=204)
def change_password(
    body: PasswordChange, request: Request, db: DB, user: CurrentUser
) -> None:
    """Change one's password (the current one is needed); other devices are
    logged out, this one stays logged in."""
    if not auth.verify_password(user.password_hash, body.current):
        raise HTTPException(403, "the current password is wrong")
    check_password_length(db, request, body.new)
    auth.change_password(db, user, body.new, keep_token=request_token(request) or "")
    db.commit()


Hint = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,40}$")]


@router.put("/hints/{hint}", status_code=204)
def mark_hint_seen(hint: Hint, db: DB, user: CurrentUser) -> None:
    """Remember that the person has seen a tutorial hint."""
    if hint not in user.seen_hints:
        user.seen_hints = [*user.seen_hints, hint]
        db.commit()


class NameFormatIn(BaseModel):
    name_format: NameFormat


@router.put("/name-format", status_code=204)
def set_name_format(body: NameFormatIn, db: DB, user: CurrentUser) -> None:
    """How the website writes people's names for the person: "Benito,
    Mónica" (family-given) or "Mónica Benito" (given-family)."""
    user.name_format = body.name_format
    db.commit()


class ProfileIn(BaseModel):
    display_name: Annotated[str, Field(max_length=100)] | None = None
    """Empty: the username is shown."""
    orcid: str | None = None
    """"0000-0002-1825-0097" or its link; empty: none."""


@router.put("/profile")
def set_profile(
    body: ProfileIn, request: Request, db: DB, user: CurrentUser
) -> UserOut:
    """One's display name and ORCID iD (Settings → Account)."""
    orcid = None
    if body.orcid and body.orcid.strip():
        orcid = authors.orcid_of(body.orcid)
        if orcid is None or not authors.valid_orcid(orcid):
            raise HTTPException(422, "not an ORCID iD (0000-0002-1825-0097)")
    user.display_name = (body.display_name or "").strip() or None
    new_orcid = orcid is not None and orcid != user.orcid
    user.orcid = orcid
    db.commit()
    if new_orcid:
        # Their papers by it, soon (if their library wants them).
        own = db.scalar(select(Library).where(Library.user_id == user.id))
        if own is not None and automations.of(own)["own_papers"]:
            queue_own_papers(request.app.state.jobs, own.id)
    return session_user_out(user, db, request)
