"""Database tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
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
    """Manages users and groups; reads no library because of it."""
    default_library_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("libraries.id", ondelete="SET NULL", use_alter=True)
    )
    """Where new items go unless another library is chosen."""


class Role(StrEnum):
    """What a member may do in a group (and every group inside it)."""

    READER = "reader"
    """Reads and searches; private tags, collections and notes only."""
    MEMBER = "member"
    """Also adds, edits and deletes items, tags and collections."""
    ADMIN = "admin"
    """Also manages members, settings and subgroups."""


ROLE_RANK = {Role.READER: 1, Role.MEMBER: 2, Role.ADMIN: 3}


class Group(Record, Base):
    """A research group; groups nest (faculty, chair, project).

    Members of a group are members of every group inside it, with the same
    role or a higher one given there; see ``paperus.access``.
    """

    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None]
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("groups.id", ondelete="RESTRICT"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class Membership(Base):
    __tablename__ = "memberships"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Library(Record, Base):
    """Where items, tags and collections live: a person's or a group's."""

    __tablename__ = "libraries"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (group_id IS NULL)", name="one_owner"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), unique=True
    )


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


class TagColor(StrEnum):
    """Colours a tag can have; the website gives each a light and dark shade."""

    GRAY = "gray"
    BROWN = "brown"
    RED = "red"
    ROSE = "rose"
    ORANGE = "orange"
    AMBER = "amber"
    YELLOW = "yellow"
    LIME = "lime"
    GREEN = "green"
    EMERALD = "emerald"
    TEAL = "teal"
    CYAN = "cyan"
    SKY = "sky"
    BLUE = "blue"
    INDIGO = "indigo"
    VIOLET = "violet"
    PURPLE = "purple"
    PINK = "pink"


class TagSource(StrEnum):
    """Who put a tag on an item (Zotero keeps manual and automatic apart)."""

    MANUAL = "manual"
    AUTOMATIC = "automatic"
    """From metadata, e.g. a registry's subjects."""
    AI = "ai"
    """Suggested by an AI assistant (shown apart until accepted)."""


class Item(Record, Trashable, Base):
    """One work (paper, book, lecture notes, meeting notes, …).

    ``type`` and ``title`` are cached from the metadata for citing: the
    preferred version's CSL-JSON plus ``overrides`` (manual edits per field;
    ``None`` removes a field). See ``paperus.library``.
    """

    __tablename__ = "items"

    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("libraries.id", ondelete="RESTRICT"), index=True
    )
    """The owner: a person's or a group's library."""
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
    tag_links: Mapped[list[ItemTag]] = relationship(
        back_populates="item", cascade="all, delete-orphan", lazy="selectin"
    )
    collection_links: Mapped[list[CollectionItem]] = relationship(
        back_populates="item", cascade="all, delete-orphan", lazy="selectin"
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
    """A normalized identifier of a version, unique in its library (checked in
    ``paperus.library``; the same paper can be in several libraries)."""

    __tablename__ = "identifiers"
    __table_args__ = (Index("ix_identifiers_scheme_value", "scheme", "value"),)

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
    in_references: Mapped[bool] = mapped_column(server_default=text("false"))
    """In the file's reference list: found by keywords, not by meaning."""


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


class SystemSetting(Base):
    """Settings changed in the admin page; environment variables give defaults."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Tag(Record, Base):
    """A label for items; names are unique per library regardless of case.

    A group's tags go only on that group's items; a person's private tags on
    any item they can read.
    """

    __tablename__ = "tags"
    __table_args__ = (
        Index(
            "ix_tags_library_name_lower", "library_id", text("lower(name)"), unique=True
        ),
    )

    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(16))
    description: Mapped[str | None]
    change: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0"), index=True
    )


class ItemTag(Base):
    __tablename__ = "item_tags"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    source: Mapped[str] = mapped_column(String(16))
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    item: Mapped[Item] = relationship(back_populates="tag_links")
    tag: Mapped[Tag] = relationship(lazy="joined", innerjoin=True)


class Collection(Record, Base):
    """A folder of items; collections nest, and an item can be in several.

    Deleting a collection deletes its subcollections, never its items. Like
    tags, a group's collections hold only that group's items; collections
    nest only within one library.
    """

    __tablename__ = "collections"

    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None]
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    change: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0"), index=True
    )


class CollectionItem(Base):
    __tablename__ = "collection_items"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    item: Mapped[Item] = relationship(back_populates="collection_links")
    collection: Mapped[Collection] = relationship(lazy="joined", innerjoin=True)
