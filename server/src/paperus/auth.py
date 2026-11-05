"""Users, passwords and login sessions."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from paperus.models import Library, LoginSession, User

SESSION_LIFETIME = timedelta(days=30)

_hasher = PasswordHasher()
# Verified against when the username is unknown, so both cases take as long.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe())


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_user(
    db: Session, username: str, password: str, *, is_admin: bool = False
) -> User:
    """A user with a private library, which is also where new items go."""
    user = User(
        username=username, password_hash=hash_password(password), is_admin=is_admin
    )
    db.add(user)
    db.flush()
    library = Library(user_id=user.id)
    db.add(library)
    db.flush()
    user.default_library_id = library.id
    return user


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        verify_password(_DUMMY_HASH, password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def start_session(db: Session, user: User) -> str:
    """Create a login session and return its token."""
    token = secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + SESSION_LIFETIME,
        )
    )
    return token


def end_session(db: Session, token: str) -> None:
    db.execute(
        delete(LoginSession).where(LoginSession.token_hash == _token_hash(token))
    )


def user_for_token(db: Session, token: str) -> User | None:
    return db.scalar(
        select(User)
        .join(LoginSession, LoginSession.user_id == User.id)
        .where(
            LoginSession.token_hash == _token_hash(token),
            LoginSession.expires_at > datetime.now(UTC),
        )
    )
