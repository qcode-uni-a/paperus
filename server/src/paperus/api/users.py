"""Users, for site administrators: create, reset passwords, roles, deactivate."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from paperus import auth
from paperus.api.admin import Admin
from paperus.api.deps import DB
from paperus.models import Item, Library, Membership, User

router = APIRouter(prefix="/api/admin/users", tags=["users"])

Username = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[\w.@+-]+$")]
Password = Annotated[str, Field(min_length=8, max_length=200)]


class UserRow(BaseModel):
    id: uuid.UUID
    username: str
    is_admin: bool
    created_at: datetime
    last_login_at: datetime | None
    deactivated_at: datetime | None
    groups: int
    """Groups the person is directly in."""
    papers: int
    """Papers the person owns privately (not in the trash)."""


class NewUser(BaseModel):
    username: Username
    password: Password
    is_admin: bool = False


class UserChange(BaseModel):
    """Only the fields given change."""

    password: Password | None = None
    """A new password; logs the person out everywhere."""
    is_admin: bool | None = None
    active: bool | None = None
    """``false`` deactivates (no login; papers and groups stay)."""


def _rows(db: DB, only: uuid.UUID | None = None) -> list[UserRow]:
    groups = dict(
        db.execute(
            select(Membership.user_id, func.count()).group_by(Membership.user_id)
        ).all()
    )
    papers = dict(
        db.execute(
            select(Library.user_id, func.count())
            .join(Item, Item.library_id == Library.id)
            .where(Library.user_id.is_not(None), Item.deleted_at.is_(None))
            .group_by(Library.user_id)
        ).all()
    )
    query = select(User).order_by(func.lower(User.username))
    if only is not None:
        query = query.where(User.id == only)
    return [
        UserRow(
            id=user.id,
            username=user.username,
            is_admin=user.is_admin,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            deactivated_at=user.deactivated_at,
            groups=groups.get(user.id, 0),
            papers=papers.get(user.id, 0),
        )
        for user in db.scalars(query)
    ]


@router.get("")
def list_users(db: DB, admin: Admin) -> list[UserRow]:
    return _rows(db)


@router.post("", status_code=201)
def create_user(body: NewUser, db: DB, admin: Admin) -> UserRow:
    """A new account (with its private space); 409 if the name is taken."""
    try:
        user = auth.create_user(
            db, body.username, body.password, is_admin=body.is_admin
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "a user of that name exists already") from error
    return _rows(db, user.id)[0]


def _active_admins(db: DB) -> int:
    return (
        db.scalar(
            select(func.count()).where(User.is_admin, User.deactivated_at.is_(None))
        )
        or 0
    )


@router.patch("/{user_id}")
def change_user(user_id: uuid.UUID, body: UserChange, db: DB, admin: Admin) -> UserRow:
    """Reset a password, grant or take admin rights, (de)activate. The last
    active administrator cannot lose those rights, and nobody deactivates
    themselves."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    losing_admin = (
        user.is_admin
        and user.deactivated_at is None
        and (body.is_admin is False or body.active is False)
    )
    if losing_admin and _active_admins(db) <= 1:
        raise HTTPException(409, "paperus needs another active administrator first")
    if body.active is False and user.id == admin.id:
        raise HTTPException(409, "you cannot deactivate yourself")
    if body.password is not None:
        user.password_hash = auth.hash_password(body.password)
        auth.end_sessions(db, user)
    if body.is_admin is not None:
        user.is_admin = body.is_admin
    if body.active is not None:
        if body.active:
            user.deactivated_at = None
        elif user.deactivated_at is None:
            user.deactivated_at = datetime.now(UTC)
            auth.end_sessions(db, user)
    db.commit()
    return _rows(db, user.id)[0]
