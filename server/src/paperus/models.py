"""Database tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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


class ChangeCounter(Base):
    """The library's change number; see ``paperus.changes``."""

    __tablename__ = "change_counters"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger)


class Trashable:
    """Objects in the trash have ``deleted_at`` set and can be restored."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class VersionKind(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PREPRINT = "preprint"
    ACCEPTED = "accepted"
    PUBLISHED = "published"
    EDITION = "edition"
    """E.g. lecture notes of one semester, or a book's 2nd edition (see label)."""
    OTHER = "other"


class MetadataSource(StrEnum):
    LOOKUP = "lookup"
    MANUAL = "manual"
    IMPORT = "import"
    SYNC = "sync"
    FILE = "file"
    """A placeholder from the uploaded file (its name or embedded title),
    replaced when a DOI or arXiv ID is found in it."""


class FileRole(StrEnum):
    MAIN = "main"
    SUPPLEMENTARY = "supplementary"
    SLIDES = "slides"
    TRANSCRIPT = "transcript"
    RECORDING = "recording"
    OTHER = "other"


class TextStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    NO_TEXT = "no_text"
    """E.g. a scanned PDF without a text layer; OCR later."""
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class FileSource(StrEnum):
    """Where a file came from; matters for sharing rules."""

    UPLOAD = "upload"
    OPEN_ACCESS = "open_access"
    BROWSER = "browser"


class Item(Record, Trashable, Base):
    """One work (paper, book, lecture notes, meeting notes, …).

    ``type`` and ``title`` are cached from the metadata for citing: the
    preferred version's CSL-JSON plus ``overrides`` (manual edits per field;
    ``None`` removes a field). See ``paperus.library``.
    """

    __tablename__ = "items"

    type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str]
    overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    change: Mapped[int] = mapped_column(BigInteger, index=True)
    """Change number of the last change to the item or its versions and files."""

    versions: Mapped[list[Version]] = relationship(
        back_populates="item",
        order_by="Version.id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Version(Record, Base):
    """One edition of an item, with its own identifiers, metadata and files."""

    __tablename__ = "versions"
    __table_args__ = (
        Index(
            "ix_versions_one_pinned_per_item",
            "item_id",
            unique=True,
            postgresql_where=text("pinned"),
        ),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    label: Mapped[str | None]
    csl: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metadata_source: Mapped[str] = mapped_column(String(32))
    pinned: Mapped[bool] = mapped_column(server_default=text("false"))
    """Use this version for citing, whatever its kind."""
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    item: Mapped[Item] = relationship(back_populates="versions")
    identifiers: Mapped[list[Identifier]] = relationship(
        back_populates="version",
        order_by="Identifier.id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    files: Mapped[list[File]] = relationship(
        back_populates="version",
        order_by="File.id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Identifier(Record, Base):
    """A normalized identifier of a version, unique in the library."""

    __tablename__ = "identifiers"
    __table_args__ = (UniqueConstraint("scheme", "value"),)

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE"), index=True
    )
    scheme: Mapped[str] = mapped_column(String(16))
    value: Mapped[str]

    version: Mapped[Version] = relationship(back_populates="identifiers")


class Blob(Base):
    """File contents, stored once per SHA-256 (see ``paperus.storage``)."""

    __tablename__ = "blobs"

    sha256: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class File(Record, Trashable, Base):
    """A file of a version; several files can share one blob."""

    __tablename__ = "files"

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE"), index=True
    )
    blob_sha256: Mapped[bytes] = mapped_column(ForeignKey("blobs.sha256"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str]
    media_type: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    text_status: Mapped[str] = mapped_column(
        String(16), server_default=TextStatus.PENDING.value, index=True
    )
    text_error: Mapped[str | None]

    version: Mapped[Version] = relationship(back_populates="files")
    blob: Mapped[Blob] = relationship(lazy="joined", innerjoin=True)


class Chunk(Base):
    """A passage of text, stored once per content hash."""

    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),)

    sha256: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    text: Mapped[str]
    # "simple": no stemming, so exact terms (gene names, acronyms) match;
    # search by meaning covers paraphrases.
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True)
    )


class FileChunk(Base):
    """The content manifest of a file: its chunks in order, with pages."""

    __tablename__ = "file_chunks"

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_sha256: Mapped[bytes] = mapped_column(ForeignKey("chunks.sha256"), index=True)
    page: Mapped[int | None]


class Embedding(Base):
    """A chunk's vector from one model; several models can coexist."""

    __tablename__ = "embeddings"

    chunk_sha256: Mapped[bytes] = mapped_column(
        ForeignKey("chunks.sha256", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    # No fixed dimension: models differ. Exact search is fast at group scale;
    # an index per model can cast to halfvec(n) later.
    embedding: Mapped[list[float]] = mapped_column(HALFVEC())
