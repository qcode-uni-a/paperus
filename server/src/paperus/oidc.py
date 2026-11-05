"""Login with OpenID Connect (OIDC): the authorization code flow with
PKCE, for any provider that publishes a discovery document (Keycloak,
Shibboleth's OIDC OP, Microsoft Entra, SATOSA in front of SAML, …).

The ID token comes straight from the provider's token endpoint over TLS, so
its signature is not checked (OpenID Connect Core 1.0, 3.1.3.7, item 6); its
issuer, audience, expiry and nonce are.
"""

import base64
import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import auth
from paperus.models import User
from paperus.system import SystemConfig

# Discovery documents are kept this long.
CACHE_SECONDS = 3600
_discovered: dict[str, tuple[float, "Provider"]] = {}
USERNAME = re.compile(r"^[\w.@+-]{1,64}$")


class LoginFailed(Exception):
    """Why an OIDC login did not work, in words for the person."""


@dataclass
class Provider:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str | None


@dataclass
class Started:
    url: str
    """Where to send the browser."""
    state: str
    nonce: str
    verifier: str


def _secure(url: str) -> bool:
    parts = urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    return parts.scheme == "https" or (parts.scheme == "http" and local)


def discover(http: httpx2.Client, issuer: str, *, fresh: bool = False) -> Provider:
    """The provider's endpoints, from its discovery document."""
    issuer = issuer.rstrip("/")
    cached = _discovered.get(issuer)
    if cached and not fresh and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    if not _secure(issuer):
        raise LoginFailed("the identity provider's address must start with https://")
    try:
        response = http.get(f"{issuer}/.well-known/openid-configuration", timeout=10)
        response.raise_for_status()
        document = response.json()
    except (httpx2.HTTPError, ValueError) as error:
        raise LoginFailed(f"the identity provider did not answer: {error}") from error
    if str(document.get("issuer", "")).rstrip("/") != issuer:
        raise LoginFailed(
            f"the provider calls itself {document.get('issuer')!r}, not {issuer!r}"
        )
    try:
        provider = Provider(
            issuer=document["issuer"],
            authorization_endpoint=document["authorization_endpoint"],
            token_endpoint=document["token_endpoint"],
            userinfo_endpoint=document.get("userinfo_endpoint"),
        )
    except KeyError as error:
        raise LoginFailed(f"the discovery document lacks {error}") from error
    if not all(
        _secure(url)
        for url in (provider.authorization_endpoint, provider.token_endpoint)
    ):
        raise LoginFailed("the provider's endpoints must use https://")
    _discovered[issuer] = (time.monotonic(), provider)
    return provider


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def start(provider: Provider, client_id: str, redirect_uri: str) -> Started:
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in provider.authorization_endpoint else "?"
    return Started(
        url=f"{provider.authorization_endpoint}{separator}{query}",
        state=state,
        nonce=nonce,
        verifier=verifier,
    )


def _claims_of(id_token: str) -> dict[str, Any]:
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
    except (IndexError, ValueError) as error:
        raise LoginFailed(
            "the identity provider sent an unreadable ID token"
        ) from error
    if not isinstance(claims, dict):
        raise LoginFailed("the identity provider sent an unreadable ID token")
    return claims


def finish(
    http: httpx2.Client,
    provider: Provider,
    *,
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    code: str,
    verifier: str,
    nonce: str,
) -> dict[str, Any]:
    """Exchange the code for the person's claims (from the ID token, and the
    userinfo endpoint for what it lacks)."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "client_id": client_id,
    }
    if client_secret:
        form["client_secret"] = client_secret
    try:
        response = http.post(provider.token_endpoint, data=form, timeout=15)
        tokens = response.json()
    except (httpx2.HTTPError, ValueError) as error:
        raise LoginFailed(f"the identity provider did not answer: {error}") from error
    if response.status_code != 200 or "id_token" not in tokens:
        reason = (
            tokens.get("error_description")
            or tokens.get("error")
            or response.status_code
        )
        raise LoginFailed(f"the identity provider refused the login: {reason}")
    claims = _claims_of(tokens["id_token"])
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if str(claims.get("iss", "")).rstrip("/") != provider.issuer.rstrip("/"):
        raise LoginFailed("the ID token comes from another issuer")
    if client_id not in audiences:
        raise LoginFailed("the ID token is meant for another client")
    if (
        not isinstance(claims.get("exp"), int | float)
        or claims["exp"] < time.time() - 60
    ):
        raise LoginFailed("the ID token has expired")
    if claims.get("nonce") != nonce:
        raise LoginFailed("the login was not started here (nonce)")
    if not claims.get("sub"):
        raise LoginFailed("the ID token names nobody (no sub)")
    if provider.userinfo_endpoint and tokens.get("access_token"):
        try:
            info = http.get(
                provider.userinfo_endpoint,
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
                timeout=10,
            ).json()
        except (httpx2.HTTPError, ValueError):
            info = {}
        if isinstance(info, dict) and info.get("sub") == claims["sub"]:
            claims = {**info, **claims}
    return claims


def user_for(db: Session, claims: dict[str, Any], config: SystemConfig) -> User:
    """The account for these claims: the one linked before, else the one of
    the same username (then linked), else a new one if allowed."""
    subject = f"{claims['iss']} {claims['sub']}"
    user = db.scalar(select(User).where(User.oidc_subject == subject))
    if user is None:
        username = str(claims.get(config.oidc_username_claim) or "")
        if not USERNAME.fullmatch(username):
            raise LoginFailed(
                f"the identity provider sent no usable {config.oidc_username_claim}"
            )
        user = db.scalar(select(User).where(User.username == username))
        if user is not None and user.oidc_subject is not None:
            raise LoginFailed(f"the account {username} belongs to another login")
        if user is None:
            if not config.oidc_create_accounts:
                raise LoginFailed(
                    f"there is no account {username} yet; ask an administrator"
                )
            user = auth.create_user(db, username, secrets.token_urlsafe(32))
        user.oidc_subject = subject
    if user.deactivated_at is not None:
        raise LoginFailed("this account is deactivated")
    user.last_login_at = datetime.now(UTC)
    return user


def link(db: Session, user: User, claims: dict[str, Any]) -> None:
    """Link the OIDC login to this account (whatever its name)."""
    subject = f"{claims['iss']} {claims['sub']}"
    other = db.scalar(select(User).where(User.oidc_subject == subject))
    if other is not None and other.id != user.id:
        raise LoginFailed(f"this OIDC login belongs to the account {other.username}")
    user.oidc_subject = subject
