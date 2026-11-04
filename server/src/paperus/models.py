"""Database tables."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, LargeBinary, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Record:
    """Columns shared by all tables: a UUIDv7 key and the creation time."""

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("uuidv7()"), sort_order=-2
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), sort_order=-1
    )


class User(Record, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str]
    is_admin: Mapped[bool] = mapped_column(server_default=text("false"))


class LoginSession(Record, Base):
    """A logged-in session; only the SHA-256 of its token is stored."""

    __tablename__ = "login_sessions"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Item(Record, Base):
    """One work (paper, book, lecture notes, …); metadata as CSL-JSON."""

    __tablename__ = "items"

    type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str]
    doi: Mapped[str | None] = mapped_column(unique=True)
    csl: Mapped[dict[str, Any]] = mapped_column(JSONB)
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class Blob(Base):
    """File contents, stored once per SHA-256 (see ``paperus.storage``)."""

    __tablename__ = "blobs"

    sha256: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VersionType(StrEnum):
    INTERNAL_DRAFT = "internal_draft"
    SUBMITTED = "submitted"
    PREPRINT = "preprint"
    ACCEPTED = "accepted"
    PUBLISHED = "published"
    SUPPLEMENTARY = "supplementary"
    SYNCED = "synced"


class FileSource(StrEnum):
    """Where a file came from; matters for sharing rules."""

    UPLOAD = "upload"
    OPEN_ACCESS = "open_access"
    BROWSER = "browser"


class File(Record, Base):
    """A file of an item; several files can share one blob."""

    __tablename__ = "files"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    blob_sha256: Mapped[bytes] = mapped_column(ForeignKey("blobs.sha256"), index=True)
    filename: Mapped[str]
    media_type: Mapped[str] = mapped_column(String(255))
    version_type: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
