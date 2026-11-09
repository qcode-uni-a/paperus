"""Personal access tokens: for scripts and AI assistants (MCP), not people.

A token acts as its user, narrowed by its scopes and optionally to some
owners (libraries); never more than the user may. Tokens never manage
accounts: no passwords, users, groups, tokens or administration.
"""

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus.models import AccessToken, User

PREFIX = "paperus_"


class Scope(StrEnum):
    SEARCH = "search"
    PAPERS_READ = "papers.read"
    """Papers, their versions, tags and collections."""
    FILES_READ = "files.read"
    """The files themselves (PDFs, notes)."""
    PAPERS_WRITE = "papers.write"
    """Add, change and trash papers and their files."""
    TAGS_WRITE = "tags.write"
    COLLECTIONS_WRITE = "collections.write"
    NOTES_WRITE = "notes.write"
    """Write, change and trash notes (reading them comes with papers.read)."""
    GROUPS_READ = "groups.read"
    """The groups and owners one belongs to (names, members)."""


PRESETS: dict[str, list[Scope]] = {
    "read": [Scope.SEARCH, Scope.PAPERS_READ, Scope.FILES_READ, Scope.GROUPS_READ],
    "assistant": [Scope.SEARCH, Scope.PAPERS_READ, Scope.FILES_READ],
    # The browser extension: add papers with their files, see which one has.
    "extension": [Scope.PAPERS_READ, Scope.PAPERS_WRITE, Scope.GROUPS_READ],
    "everything": list(Scope),
}


def _hash(raw: str) -> bytes:
    return hashlib.sha256(raw.encode()).digest()


def is_token(raw: str) -> bool:
    return raw.startswith(PREFIX)


def create_token(
    db: Session,
    user: User,
    name: str,
    scopes: list[Scope],
    *,
    library_ids: list[uuid.UUID] | None = None,
    expires_in: timedelta | None = None,
) -> tuple[AccessToken, str]:
    """A new token and its value (shown once; only the hash is kept)."""
    raw = PREFIX + secrets.token_urlsafe(32)
    token = AccessToken(
        user_id=user.id,
        name=name,
        token_hash=_hash(raw),
        hint=raw[: len(PREFIX) + 4] + "…",
        scopes=sorted({str(scope) for scope in scopes}),
        library_ids=[str(i) for i in library_ids] if library_ids is not None else None,
        expires_at=datetime.now(UTC) + expires_in if expires_in else None,
    )
    db.add(token)
    db.flush()
    return token, raw


def find_token(db: Session, raw: str) -> tuple[AccessToken, User] | None:
    """The token and its user, if it is valid (not expired, user active)."""
    row = db.execute(
        select(AccessToken, User)
        .join(User, User.id == AccessToken.user_id)
        .where(AccessToken.token_hash == _hash(raw), User.deactivated_at.is_(None))
    ).first()
    if row is None:
        return None
    token, user = row
    now = datetime.now(UTC)
    if token.expires_at is not None and token.expires_at <= now:
        return None
    # Remember the use, but not on every request.
    if token.last_used_at is None or now - token.last_used_at > timedelta(minutes=1):
        token.last_used_at = now
        db.commit()
    return token, user


# Which scope each API call needs (method, path pattern); anything not
# listed is closed to tokens.
_READ = ("GET", "HEAD")
_RULES: list[tuple[tuple[str, ...], re.Pattern[str], Scope]] = [
    (_READ, re.compile(r"/api/search"), Scope.SEARCH),
    (_READ, re.compile(r"/api/files/[^/]+/(content|annotated)"), Scope.FILES_READ),
    (_READ, re.compile(r"/api/files/[^/]+/passages/[^/]+"), Scope.FILES_READ),
    (
        _READ,
        re.compile(r"/api/(items|tags|collections|authors)(/.*)?"),
        Scope.PAPERS_READ,
    ),
    (_READ, re.compile(r"/api/citations"), Scope.PAPERS_READ),
    (_READ, re.compile(r"/api/duplicates"), Scope.PAPERS_READ),
    (_READ, re.compile(r"/api/notes(/.*)?"), Scope.PAPERS_READ),
    (
        ("POST", "PUT", "PATCH", "DELETE"),
        re.compile(r"/api/notes(/.*)?"),
        Scope.NOTES_WRITE,
    ),
    (_READ, re.compile(r"/api/files/[^/]+/annotations"), Scope.PAPERS_READ),
    # Annotations are one's own, like notes (readers of a paper make them).
    (
        ("POST", "PUT", "PATCH", "DELETE"),
        re.compile(
            r"/api/(files/[^/]+/annotations|annotations/[^/]+"
            r"|items/[^/]+/annotation-sharing)"
        ),
        Scope.NOTES_WRITE,
    ),
    (_READ, re.compile(r"/api/uploads/[^/]+"), Scope.PAPERS_READ),
    (_READ, re.compile(r"/api/(libraries|groups)(/.*)?"), Scope.GROUPS_READ),
    (_READ, re.compile(r"/api/auth/me"), Scope.PAPERS_READ),
    (("POST", "DELETE"), re.compile(r"/api/items/[^/]+/tags(/.*)?"), Scope.TAGS_WRITE),
    (("POST", "PATCH", "DELETE"), re.compile(r"/api/tags(/.*)?"), Scope.TAGS_WRITE),
    (
        ("POST", "PATCH", "DELETE"),
        re.compile(r"/api/collections(/.*)?"),
        Scope.COLLECTIONS_WRITE,
    ),
    (
        ("POST", "PUT", "PATCH", "DELETE"),
        re.compile(r"/api/(items|versions|files|uploads)(/.*)?"),
        Scope.PAPERS_WRITE,
    ),
]


# A person's own view of the library (stars, pinned collections, what they
# opened), imports (they make collections), and changes to many papers at
# once (the website's selection: they need several scopes; assistants have
# their own tools): not for assistants and scripts, even where a rule above
# matches.
_CLOSED = re.compile(
    r"/api/(items/[^/]+/(favourite|viewed|references/import)"
    r"|items/bulk|collections/[^/]+/pin)"
)


def needed_scope(method: str, path: str) -> Scope | None:
    """The scope a call needs, or None if tokens may not make it at all.
    Every route's answer is pinned in tests/test_tokens.py, so a new route
    needs a decision."""
    if _CLOSED.fullmatch(path):
        return None
    for methods, pattern, scope in _RULES:
        if method in methods and pattern.fullmatch(path):
            return scope
    return None


def allows(token: AccessToken, method: str, path: str) -> bool:
    scope = needed_scope(method, path)
    return scope is not None and scope in token.scopes
