"""Users, passwords and login sessions."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from paperus.models import Group, Library, LoginSession, Membership, User

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


def join_groups(db: Session, user: User, groups: list[tuple[uuid.UUID, str]]) -> None:
    """Make a new account a member of these groups (with these roles);
    groups deleted meanwhile are skipped."""
    existing = set(
        db.scalars(select(Group.id).where(Group.id.in_([g for g, _ in groups])))
    )
    for group_id, role in groups:
        if group_id in existing:
            db.add(Membership(group_id=group_id, user_id=user.id, role=role))
    db.flush()


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        verify_password(_DUMMY_HASH, password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    if user.deactivated_at is not None:
        return None
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    return user


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def start_session(
    db: Session, user: User, lifetime: timedelta = SESSION_LIFETIME
) -> str:
    """Create a login session and return its token."""
    token = secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + lifetime,
        )
    )
    return token


def end_session(db: Session, token: str) -> None:
    db.execute(
        delete(LoginSession).where(LoginSession.token_hash == _token_hash(token))
    )


def end_sessions(db: Session, user: User) -> None:
    """Log the user out everywhere."""
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))


def end_all_sessions(db: Session, keep_token: str) -> int:
    """Log everyone out, except the session ``keep_token``; how many ended."""
    result = db.execute(
        delete(LoginSession).where(LoginSession.token_hash != _token_hash(keep_token))
    )
    return int(getattr(result, "rowcount", 0) or 0)


def change_password(db: Session, user: User, password: str, keep_token: str) -> None:
    """Set a new password and end every other login session of the user."""
    user.password_hash = hash_password(password)
    db.execute(
        delete(LoginSession).where(
            LoginSession.user_id == user.id,
            LoginSession.token_hash != _token_hash(keep_token),
        )
    )


def user_for_token(db: Session, token: str) -> User | None:
    return db.scalar(
        select(User)
        .join(LoginSession, LoginSession.user_id == User.id)
        .where(
            LoginSession.token_hash == _token_hash(token),
            LoginSession.expires_at > datetime.now(UTC),
            User.deactivated_at.is_(None),
        )
    )
