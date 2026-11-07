"""OAuth 2.1 for connected apps: AI assistants that connect to the MCP
server as remote connectors (claude.ai, ChatGPT), which take no token by
hand.

paperus is its own authorization server, as the MCP specification
describes: apps register themselves (dynamic client registration, public
clients without a secret), the person logs in to the website and allows
the app what it may do, and the app exchanges the one-time code (with its
PKCE verifier) for an access token and a refresh token. Access tokens are
ordinary access tokens (``paperus.tokens``) that expire after an hour;
the refresh token is replaced on every use. Deleting the grant (Settings →
Connected apps) disconnects the app at once.
"""

import base64
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from paperus import tokens
from paperus.models import AccessToken, OAuthClient, OAuthCode, OAuthGrant, User
from paperus.tokens import Scope

ACCESS_LIFETIME = timedelta(hours=1)
REFRESH_LIFETIME = timedelta(days=90)
"""Unused this long, a connection ends (each use renews it)."""
CODE_LIFETIME = timedelta(minutes=10)
UNUSED_CLIENT = timedelta(days=1)
"""Registrations never allowed by anyone are removed after this."""
REFRESH_PREFIX = "paperusr_"
MAX_REDIRECT_URIS = 10
# Schemes a browser must never be sent to with a code.
_UNSAFE_SCHEMES = {"javascript", "data", "file", "vbscript", "blob", "about"}
LOOPBACK = {"localhost", "127.0.0.1", "::1"}

DEFAULT_SCOPES = [Scope.SEARCH, Scope.PAPERS_READ, Scope.FILES_READ]
"""Allowed when an app asks for nothing in particular: reading only."""


class OAuthError(Exception):
    """An error as OAuth names it (``invalid_grant``, …)."""

    def __init__(self, error: str, description: str) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


def _hash(raw: str) -> bytes:
    return hashlib.sha256(raw.encode()).digest()


def valid_redirect(uri: str) -> bool:
    """HTTPS; plain HTTP only back to this computer (an app on the
    desktop); or an app's own scheme (``cursor://…``). No fragments."""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    scheme = parts.scheme.lower()
    if not scheme or parts.fragment or scheme in _UNSAFE_SCHEMES:
        return False
    if scheme == "https":
        return bool(parts.hostname)
    if scheme == "http":
        return parts.hostname in LOOPBACK
    # An app's own scheme (RFC 8252): needs a path or host to go to.
    return bool(parts.netloc or parts.path)


def _same_redirect(registered: str, given: str) -> bool:
    """Exact match; for loopback addresses any port (RFC 8252 7.3: desktop
    apps pick a free port each time)."""
    if registered == given:
        return True
    a, b = urlsplit(registered), urlsplit(given)
    return (
        a.scheme == b.scheme == "http"
        and a.hostname in LOOPBACK
        and a.hostname == b.hostname
        and a.path == b.path
        and a.query == b.query
    )


def register_client(db: Session, name: str, redirect_uris: list[str]) -> OAuthClient:
    """A new app (``ValueError`` for unusable redirect addresses). Old
    registrations that nobody ever allowed are removed meanwhile."""
    if not redirect_uris or len(redirect_uris) > MAX_REDIRECT_URIS:
        raise ValueError(f"give 1 to {MAX_REDIRECT_URIS} redirect_uris")
    for uri in redirect_uris:
        if len(uri) > 2000 or not valid_redirect(uri):
            raise ValueError(f"redirect_uri not allowed: {uri[:200]}")
    used = select(OAuthGrant.client_id)
    db.execute(
        delete(OAuthClient).where(
            OAuthClient.created_at < datetime.now(UTC) - UNUSED_CLIENT,
            OAuthClient.id.not_in(used),
        )
    )
    client = OAuthClient(
        client_id=secrets.token_urlsafe(24),
        name=" ".join(name.split())[:200] or "An app",
        redirect_uris=redirect_uris,
    )
    db.add(client)
    db.flush()
    return client


def find_client(db: Session, client_id: str) -> OAuthClient | None:
    return db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))


@dataclass
class Asked:
    """An app's request to be allowed, checked."""

    client: OAuthClient
    redirect_uri: str
    scopes: list[Scope]
    """What it asks for (known scopes only; reading if it named none)."""


def check_request(
    db: Session,
    *,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str | None,
) -> Asked:
    """The request if it can be shown to the person. ``OAuthError`` with
    ``invalid_client`` or ``invalid_redirect`` must not be sent back to the
    redirect address (it is not trusted); others may."""
    client = find_client(db, client_id)
    if client is None:
        raise OAuthError("invalid_client", "This app is not registered here.")
    if not any(_same_redirect(r, redirect_uri) for r in client.redirect_uris):
        raise OAuthError(
            "invalid_redirect", "The app gave an address it did not register."
        )
    if response_type != "code":
        raise OAuthError("unsupported_response_type", "Only response_type=code.")
    if code_challenge_method != "S256" or not 43 <= len(code_challenge) <= 128:
        raise OAuthError("invalid_request", "PKCE with S256 is required.")
    known = {s.value: s for s in Scope}
    asked = [known[s] for s in (scope or "").split() if s in known]
    return Asked(client, redirect_uri, sorted(set(asked) or DEFAULT_SCOPES))


def create_code(
    db: Session,
    asked: Asked,
    user: User,
    scopes: list[Scope],
    code_challenge: str,
) -> str:
    """A one-time code for what the person allowed."""
    raw = secrets.token_urlsafe(32)
    db.add(
        OAuthCode(
            code_hash=_hash(raw),
            client_id=asked.client.id,
            user_id=user.id,
            redirect_uri=asked.redirect_uri,
            code_challenge=code_challenge,
            scopes=sorted({s.value for s in scopes}),
            expires_at=datetime.now(UTC) + CODE_LIFETIME,
        )
    )
    db.flush()
    return raw


@dataclass
class Issued:
    access_token: str
    refresh_token: str
    expires_in: int
    scopes: list[str]


def _verifier_matches(verifier: str, challenge: str) -> bool:
    if not 43 <= len(verifier) <= 128:
        return False
    digest = hashlib.sha256(verifier.encode("ascii", "replace")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return secrets.compare_digest(expected, challenge)


def _issue(db: Session, grant: OAuthGrant, user: User) -> Issued:
    """A new access token and refresh token for the grant (the old refresh
    token stops working; expired access tokens are removed)."""
    now = datetime.now(UTC)
    db.execute(
        delete(AccessToken).where(
            AccessToken.grant_id == grant.id, AccessToken.expires_at <= now
        )
    )
    token, raw = tokens.create_token(
        db,
        user,
        grant.client.name[:100],
        [Scope(s) for s in grant.scopes],
        expires_in=ACCESS_LIFETIME,
    )
    token.grant_id = grant.id
    refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
    grant.refresh_hash = _hash(refresh)
    grant.refresh_expires_at = now + REFRESH_LIFETIME
    grant.last_used_at = now
    db.flush()
    return Issued(raw, refresh, int(ACCESS_LIFETIME.total_seconds()), grant.scopes)


def exchange_code(
    db: Session, *, client_id: str, code: str, redirect_uri: str, verifier: str
) -> Issued:
    """Tokens for a code (once; ``OAuthError`` otherwise)."""
    client = find_client(db, client_id)
    if client is None:
        raise OAuthError("invalid_client", "Unknown client_id.")
    found = db.scalar(
        select(OAuthCode).where(OAuthCode.code_hash == _hash(code)).with_for_update()
    )
    if found is None or found.client_id != client.id:
        raise OAuthError("invalid_grant", "The code is unknown or already used.")
    db.delete(found)
    db.flush()
    if found.expires_at <= datetime.now(UTC):
        raise OAuthError("invalid_grant", "The code has expired.")
    if found.redirect_uri != redirect_uri:
        raise OAuthError("invalid_grant", "redirect_uri differs from the request.")
    if not _verifier_matches(verifier, found.code_challenge):
        raise OAuthError("invalid_grant", "The PKCE code_verifier does not match.")
    user = db.get(User, found.user_id)
    if user is None or user.deactivated_at is not None:
        raise OAuthError("invalid_grant", "The account is not active.")
    grant = OAuthGrant(
        client_id=client.id,
        user_id=user.id,
        scopes=found.scopes,
        refresh_hash=b"",
        refresh_expires_at=datetime.now(UTC),
    )
    grant.client = client
    db.add(grant)
    db.flush()
    return _issue(db, grant, user)


def refresh(db: Session, *, client_id: str, refresh_token: str) -> Issued:
    """New tokens for a refresh token (which is then used up)."""
    grant = db.scalar(
        select(OAuthGrant)
        .where(OAuthGrant.refresh_hash == _hash(refresh_token))
        .with_for_update(of=OAuthGrant)
    )
    if grant is None or grant.client.client_id != client_id:
        raise OAuthError("invalid_grant", "The refresh token is unknown or used.")
    if grant.refresh_expires_at <= datetime.now(UTC):
        db.delete(grant)
        db.flush()
        raise OAuthError("invalid_grant", "The connection has expired.")
    user = db.get(User, grant.user_id)
    if user is None or user.deactivated_at is not None:
        raise OAuthError("invalid_grant", "The account is not active.")
    return _issue(db, grant, user)


def revoke(db: Session, raw: str) -> None:
    """Ends the connection a refresh or access token belongs to (RFC 7009:
    unknown tokens are no error)."""
    if raw.startswith(REFRESH_PREFIX):
        grant = db.scalar(
            select(OAuthGrant).where(OAuthGrant.refresh_hash == _hash(raw))
        )
        if grant is not None:
            db.delete(grant)
    elif tokens.is_token(raw):
        found = tokens.find_token(db, raw)
        if found is not None and found[0].grant_id is not None:
            db.execute(delete(OAuthGrant).where(OAuthGrant.id == found[0].grant_id))
    db.flush()


def grants_of(db: Session, user_id: uuid.UUID) -> list[OAuthGrant]:
    return list(
        db.scalars(
            select(OAuthGrant)
            .where(OAuthGrant.user_id == user_id)
            .order_by(OAuthGrant.created_at.desc())
        )
    )
