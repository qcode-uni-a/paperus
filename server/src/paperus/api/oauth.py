"""OAuth for connected apps (see ``paperus.oauth``): the metadata apps
discover, registration, the person's consent (shown by the website at
``/oauth/authorize``), tokens, and the person's list of connected apps."""

import base64
import binascii
import uuid
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Form, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete

from paperus import oauth
from paperus.api.auth import public_base
from paperus.api.deps import DB, SessionUser
from paperus.models import OAuthGrant
from paperus.system import load_config
from paperus.tokens import Scope

router = APIRouter(tags=["oauth"])


def _base(request: Request, db: DB) -> str:
    return public_base(request, load_config(db, request.app.state.settings))


def _resource_metadata(request: Request, db: DB) -> dict[str, Any]:
    base = _base(request, db)
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "scopes_supported": [s.value for s in Scope],
        "bearer_methods_supported": ["header"],
        "resource_name": "paperus",
    }


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def resource_metadata(request: Request, db: DB) -> dict[str, Any]:
    """Where apps learn how to get a token for the MCP server (RFC 9728)."""
    return _resource_metadata(request, db)


@router.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
def mcp_resource_metadata(request: Request, db: DB) -> dict[str, Any]:
    return _resource_metadata(request, db)


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
def server_metadata(request: Request, db: DB) -> dict[str, Any]:
    """paperus as authorization server (RFC 8414)."""
    base = _base(request, db)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/api/oauth/token",
        "registration_endpoint": f"{base}/api/oauth/register",
        "revocation_endpoint": f"{base}/api/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [s.value for s in Scope],
        "authorization_response_iss_parameter_supported": True,
    }


def _error(error: oauth.OAuthError, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error.error, "error_description": error.description},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


class Registration(BaseModel):
    """RFC 7591; fields not listed are ignored."""

    redirect_uris: list[str] = Field(max_length=oauth.MAX_REDIRECT_URIS)
    client_name: Annotated[str, Field(max_length=200)] = "An app"


@router.post("/api/oauth/register", status_code=201, include_in_schema=False)
def register(body: Registration, db: DB) -> JSONResponse:
    """An app registers itself (no secret: a public client with PKCE)."""
    try:
        client = oauth.register_client(db, body.client_name, body.redirect_uris)
    except ValueError as error:
        return _error(oauth.OAuthError("invalid_redirect_uri", str(error)))
    db.commit()
    return JSONResponse(
        {
            "client_id": client.client_id,
            "client_id_issued_at": int(client.created_at.timestamp()),
            "client_name": client.name,
            "redirect_uris": client.redirect_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )


class ConsentRequest(BaseModel):
    """What the app asked for (the authorization request's parameters)."""

    client_id: str
    redirect_uri: str
    response_type: str = "code"
    code_challenge: str = ""
    code_challenge_method: str = ""
    scope: str | None = None
    state: str | None = None


class ConsentInfo(BaseModel):
    client_name: str
    redirect_host: str
    """Where the person is sent back to (shown, to recognise the app)."""
    scopes: list[Scope]
    """What the app asks for."""
    username: str


def _checked(db: DB, body: ConsentRequest) -> oauth.Asked:
    try:
        return oauth.check_request(
            db,
            client_id=body.client_id,
            redirect_uri=body.redirect_uri,
            response_type=body.response_type,
            code_challenge=body.code_challenge,
            code_challenge_method=body.code_challenge_method,
            scope=body.scope,
        )
    except oauth.OAuthError as error:
        raise HTTPException(400, error.description) from error


@router.post("/api/oauth/consent/check")
def check_consent(body: ConsentRequest, db: DB, user: SessionUser) -> ConsentInfo:
    """The app and what it asks for, to show the person (only logged in,
    never with a token)."""
    asked = _checked(db, body)
    parts = urlsplit(asked.redirect_uri)
    return ConsentInfo(
        client_name=asked.client.name,
        redirect_host=parts.netloc or f"{parts.scheme}:",
        scopes=asked.scopes,
        username=user.username,
    )


class Consent(ConsentRequest):
    allow: bool
    scopes: list[Scope] = []
    """What the person allows (at most what was asked)."""


class Redirect(BaseModel):
    redirect: str
    """Where to send the browser: back to the app, with a code or an error."""


@router.post("/api/oauth/consent")
def give_consent(
    request: Request, body: Consent, db: DB, user: SessionUser
) -> Redirect:
    """The person allows the app (or not); the app gets a one-time code."""
    asked = _checked(db, body)
    params = {"state": body.state} if body.state is not None else {}
    params["iss"] = _base(request, db)
    allowed = [scope for scope in body.scopes if scope in asked.scopes]
    if body.allow and allowed:
        params["code"] = oauth.create_code(
            db, asked, user, allowed, body.code_challenge
        )
        db.commit()
    else:
        params["error"] = "access_denied"
    separator = "&" if urlsplit(asked.redirect_uri).query else "?"
    return Redirect(redirect=f"{asked.redirect_uri}{separator}{urlencode(params)}")


def _basic_client(authorization: str | None) -> str | None:
    """The client_id from HTTP Basic, for apps that send it that way."""
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(value).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    return decoded.partition(":")[0] or None


@router.post("/api/oauth/token", include_in_schema=False)
def token(
    db: DB,
    grant_type: Annotated[str, Form()],
    code: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    code_verifier: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
    client_id: Annotated[str | None, Form()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Tokens for a code (with the PKCE verifier) or a refresh token."""
    client = client_id or _basic_client(authorization)
    try:
        if client is None:
            raise oauth.OAuthError("invalid_client", "client_id is missing.")
        if grant_type == "authorization_code":
            if not (code and redirect_uri and code_verifier):
                raise oauth.OAuthError(
                    "invalid_request", "code, redirect_uri and code_verifier needed."
                )
            issued = oauth.exchange_code(
                db,
                client_id=client,
                code=code,
                redirect_uri=redirect_uri,
                verifier=code_verifier,
            )
        elif grant_type == "refresh_token":
            if not refresh_token:
                raise oauth.OAuthError("invalid_request", "refresh_token needed.")
            issued = oauth.refresh(db, client_id=client, refresh_token=refresh_token)
        else:
            raise oauth.OAuthError(
                "unsupported_grant_type", f"Not supported: {grant_type}."
            )
    except oauth.OAuthError as error:
        # A used code or an expired connection stays gone.
        db.commit()
        return _error(error, 401 if error.error == "invalid_client" else 400)
    db.commit()
    return JSONResponse(
        {
            "access_token": issued.access_token,
            "token_type": "Bearer",
            "expires_in": issued.expires_in,
            "refresh_token": issued.refresh_token,
            "scope": " ".join(issued.scopes),
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.post("/api/oauth/revoke", include_in_schema=False)
def revoke(db: DB, token: Annotated[str, Form()]) -> Response:
    """Disconnect the app the token belongs to (RFC 7009)."""
    oauth.revoke(db, token)
    db.commit()
    return Response(status_code=200)


class ConnectedApp(BaseModel):
    id: uuid.UUID
    name: str
    scopes: list[Scope]
    created_at: datetime
    """When the person allowed it."""
    last_used_at: datetime | None
    """When it last got a new access token (about hourly while in use)."""


@router.get("/api/me/connected-apps")
def connected_apps(db: DB, user: SessionUser) -> list[ConnectedApp]:
    """Apps the person allowed to act for them (OAuth), newest first."""
    return [
        ConnectedApp(
            id=grant.id,
            name=grant.client.name,
            scopes=[Scope(s) for s in grant.scopes],
            created_at=grant.created_at,
            last_used_at=grant.last_used_at,
        )
        for grant in oauth.grants_of(db, user.id)
    ]


@router.delete("/api/me/connected-apps/{grant_id}", status_code=204)
def disconnect_app(grant_id: uuid.UUID, db: DB, user: SessionUser) -> Response:
    """The app loses access at once (its tokens stop working)."""
    db.execute(
        delete(OAuthGrant).where(
            OAuthGrant.id == grant_id, OAuthGrant.user_id == user.id
        )
    )
    db.commit()
    return Response(status_code=204)
