"""Database tables."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    case,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    column_property,
    mapped_column,
    relationship,
)


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
    seen_hints: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    """Tutorial hints the person has seen (so they show once, on any device)."""
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the person last used paperus in any way (the website, the app,
    the extension, an assistant), to a few minutes."""
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Deactivated people cannot log in; their papers and memberships stay."""
    oidc_subject: Mapped[str | None] = mapped_column(String(500), unique=True)
    """Who the person is at the identity provider (issuer and subject), once
    they logged in with the OIDC login."""
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    """The profile picture: a small PNG, JPEG or WebP (see ``paperus.avatars``)."""
    avatar_type: Mapped[str | None] = mapped_column(String(32))
    avatar_version: Mapped[str | None] = mapped_column(String(16))
    """Changes with the picture, so its address can be cached for good."""
    handed_over: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """The last hand-over of their own library while they were deactivated
    (``at``, ``to``, ``by``, ``papers``), shown to them if they come back."""
    display_name: Mapped[str | None] = mapped_column(String(100))
    """Shown to others instead of the username, if set."""
    orcid: Mapped[str | None] = mapped_column(String(19))
    """Their own ORCID iD: the author with it is them (seen only by them)."""
    name_format: Mapped[str] = mapped_column(
        String(16), server_default=text("'family-given'")
    )
    """How the website writes people's names: "family-given" ("Benito,
    Mónica") or "given-family" ("Mónica Benito")."""


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
    people: Mapped[bool] = mapped_column(server_default=text("false"))
    """A few people sharing papers ("Anna & Ben", #16): made by sharing with
    someone, by anyone; all its members equal (admins), no groups inside."""


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
        CheckConstraint(
            "(user_id IS NULL) <> (group_id IS NULL)", name="ck_libraries_one_owner"
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), unique=True
    )
    automations: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    """What its owner switched of what paperus does by itself for its papers
    (``paperus.automations``); unset: the default. A person's own also
    where their papers go."""
    own_papers_seen: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    """A person's own library: DOIs of their works the daily job added or
    found already, never added again (``paperus.own_papers``)."""


class LoginSession(Record, Base):
    """A logged-in session; only the SHA-256 of its token is stored."""

    __tablename__ = "login_sessions"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccessToken(Record, Base):
    """A personal token for scripts and AI assistants (see
    ``paperus.tokens``); only its SHA-256 is stored."""

    __tablename__ = "access_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    hint: Mapped[str] = mapped_column(String(32))
    """The token's start, to recognise it (``paperus_ab12…``)."""
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    library_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    """Only these owners' things (libraries); all the user's if None."""
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("oauth_grants.id", ondelete="CASCADE"), index=True
    )
    """Issued to a connected app (OAuth), short-lived; not listed as the
    person's own tokens."""


class OAuthClient(Record, Base):
    """An app that registered itself to connect (OAuth dynamic client
    registration, e.g. Claude or ChatGPT); a public client, no secret."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    redirect_uris: Mapped[list[str]] = mapped_column(JSONB)


class OAuthCode(Record, Base):
    """A one-time authorization code, given after the person allowed the
    app; exchanged for tokens with the PKCE verifier."""

    __tablename__ = "oauth_codes"

    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    redirect_uri: Mapped[str]
    code_challenge: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthGrant(Record, Base):
    """A connected app: what the person allowed it, and its current refresh
    token (replaced on every use). Deleting it disconnects the app."""

    __tablename__ = "oauth_grants"

    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    refresh_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client: Mapped[OAuthClient] = relationship(lazy="joined")


class ChangeCounter(Base):
    """The library's change number; see ``paperus.changes``."""

    __tablename__ = "change_counters"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger)


class Removal(Base):
    """Something deleted for good, for syncing (``paperus.changes``): a
    device that last synced before ``change`` removes it too. What goes to
    the trash is a change, not a removal; what goes with a removed paper
    (its versions, files, annotations) is not listed again."""

    __tablename__ = "removals"

    record_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    """``item``, ``note``, ``tag``, ``collection``, ``file`` or ``annotation``."""
    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), index=True
    )
    """Where it was: who may read that library is told."""
    change: Mapped[int] = mapped_column(BigInteger, index=True)
    removed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    """Kept a year (``changes.KEEP_REMOVALS``)."""


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
    ERRATUM = "erratum"
    """A correction the journal published to the paper, with its own DOI
    (``paperus.errata``); never the version cited or shown."""
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
    CODE = "code"
    DATA = "data"
    SLIDES = "slides"
    PEER_REVIEW = "peer_review"
    """Referees' reports and the authors' replies (Nature's "Peer Review
    File"), as the browser extension recognises them on the page."""
    TRANSCRIPT = "transcript"
    RECORDING = "recording"
    OTHER = "other"


class LinkKind(StrEnum):
    """What a paper's link leads to."""

    CODE = "code"
    DATA = "data"
    PEER_REVIEW = "peer_review"
    """The paper's published reviews, on a page of their own (eLife's,
    PLOS's, SciPost's)."""
    OTHER = "other"


class TextStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    NO_TEXT = "no_text"
    """E.g. a scanned PDF without a text layer (see OcrStatus)."""
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class OcrStatus(StrEnum):
    """Pages without text (scans) are read by OCR in the ML service;
    ``None``: the file has none."""

    PENDING = "pending"
    DONE = "done"
    """Its scanned pages are read; their text is in the file's passages."""
    SKIPPED = "skipped"
    """OCR is switched off (Administration → Settings → Machine learning)."""
    FAILED = "failed"


class FileSource(StrEnum):
    """Where a file came from; matters for sharing rules."""

    UPLOAD = "upload"
    OPEN_ACCESS = "open_access"
    BROWSER = "browser"
    IMPORT = "import"
    """From another reference manager's export."""


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
    """From the paper's details (arXiv categories, a publisher's subjects,
    the authors' keywords); shown as its keywords, apart from tags."""
    AI = "ai"
    """Suggested by an AI assistant (shown apart until accepted)."""


class Item(Record, Trashable, Base):
    """One work (paper, book, lecture notes, meeting notes, …).

    ``type`` and ``title`` are cached from the metadata for citing: the
    preferred version's CSL-JSON plus ``overrides`` (manual edits per field;
    ``None`` removes a field). See ``paperus.library``.
    """

    __tablename__ = "items"
    __table_args__ = (
        # The words of titles (stems, without stop words), to find papers
        # whose titles share words (``duplicates.titled_alike``).
        Index(
            "ix_items_title_words",
            text("tsvector_to_array(to_tsvector('english'::regconfig, title))"),
            postgresql_using="gin",
        ),
    )

    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("libraries.id", ondelete="RESTRICT"), index=True
    )
    """The owner: a person's or a group's library."""
    type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str]
    year: Mapped[int | None] = mapped_column(index=True)
    """Of publication, as cited (for smart collections' rules)."""
    issued_from: Mapped[date | None] = mapped_column(index=True)
    issued_to: Mapped[date | None] = mapped_column(index=True)
    """The days the publication date stands for: one day, a month (March
    2024: 1 to 31 March) or a year, as precisely as it is known."""
    first_author: Mapped[str | None] = mapped_column(Text)
    """As cited ("Family, Given", or a name as it stands), for sorting."""
    journal: Mapped[str | None] = mapped_column(Text)
    """The journal or venue as cited (``container-title``), for sorting."""
    file_wanted: Mapped[bool] = mapped_column(server_default=text("true"))
    """False: no file is needed (a web page, a book on the shelf); not
    listed under Manage → Missing."""
    open_access_tried_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    open_access_error: Mapped[str | None] = mapped_column(Text)
    """Why the last try found no open-access copy."""
    published_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    """A preprint: when paperus last looked for its published version."""
    errata_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When paperus last looked for corrections to it (``paperus.errata``)."""
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Kept for good, but left out of lists and search unless asked for."""
    references_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    """When paperus last looked for the paper's reference list."""
    references_source: Mapped[str | None] = mapped_column(String(16))
    """Where its reference list came from (``arxiv``, ``crossref``, ``pdf``);
    None: none found (yet)."""
    authors_key: Mapped[str | None] = mapped_column(String(64))
    """A hash of the paper's author names (set with its details); when it
    differs from ``authors_linked``, its authors wait to be linked to
    people (``paperus.authors``)."""
    authors_linked: Mapped[str | None] = mapped_column(String(64))
    authors_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When its authors were looked up at OpenAlex (``paperus.authors``)."""
    abstract: Mapped[str | None] = mapped_column(Text)
    """Found elsewhere while its details have none: OpenAlex's, else the
    PDF's (``paperus.abstracts``)."""
    overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    links: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    """Where its code, data and more are: ``{"url", "kind", "label"}`` each
    (``LinkKind``), from a person or the publisher's page (the browser
    extension); see ``library.add_links``."""
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    change: Mapped[int] = mapped_column(BigInteger, index=True)
    """Change number of the last change to the item or its versions and files."""
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    """When that change happened (stamped with the change number)."""

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
    favourites: Mapped[list[Favourite]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    """Who starred it (lists show each person only their own star)."""
    authorships: Mapped[list[Authorship]] = relationship(
        order_by="Authorship.position",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    """Its authors as people (``paperus.authors``)."""


class ItemReference(Base):
    """One entry of a paper's reference list (see ``paperus.item_references``),
    with the identifiers found in it, normalized like ``Identifier``'s."""

    __tablename__ = "item_references"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    """From 1, in the order of the list."""
    text: Mapped[str]
    """The reference as printed, without LaTeX."""
    title: Mapped[str | None]
    authors: Mapped[str | None]
    """Short: "Smith et al.", "Smith and Jones"."""
    year: Mapped[int | None]
    container: Mapped[str | None]
    """The journal or book it appeared in."""
    doi: Mapped[str | None] = mapped_column(index=True)
    arxiv: Mapped[str | None] = mapped_column(index=True)
    url: Mapped[str | None]


class Author(Record, Base):
    """A person who wrote papers, shared by the whole installation (authors
    are public facts; who sees which papers is up to ``Access``). See
    ``paperus.authors``."""

    __tablename__ = "authors"

    name: Mapped[str]
    """As shown: "Mónica Benito" (the fullest spelling seen)."""
    key: Mapped[str] = mapped_column(index=True)
    """The name folded (``authors.fold``): what "the same full name" means."""
    orcid: Mapped[str | None] = mapped_column(String(19), unique=True)
    openalex_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    if TYPE_CHECKING:
        written: str | None
        """The name as on their papers, "Benito, Mónica" (the spelling
        shown first); set below, after ``Authorship``."""


class AuthorSource(StrEnum):
    """How a paper's author was linked to a person."""

    NAME = "name"
    """The same full name."""
    ORCID = "orcid"
    OPENALEX = "openalex"
    HAND = "hand"
    """By a person; automatic passes leave it alone."""


class Authorship(Base):
    """An author of a paper, at their place in its author list, linked to
    the person (none yet: to check, e.g. a name several people share)."""

    __tablename__ = "authorships"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    """From 1, in the order of the paper's authors."""
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("authors.id", ondelete="SET NULL"), index=True
    )
    written: Mapped[str]
    """The name as on this paper: "Benito, M." ("Family, Given")."""
    key: Mapped[str] = mapped_column(index=True)
    """``written`` folded."""
    source: Mapped[str] = mapped_column(String(16))
    """``AuthorSource``."""
    affiliation: Mapped[str | None]
    """Where they were for this paper (it changes over time)."""
    orcid: Mapped[str | None] = mapped_column(String(19))
    openalex_id: Mapped[str | None] = mapped_column(String(32))
    """The ids this paper's details give for the author."""


def _given_family(written: Any) -> Any:  # noqa: ANN401 (SQL expressions)
    """ "Benito, Mónica" → "Mónica Benito" in SQL (``authors._shown``)."""
    comma = func.strpos(written, ",")
    given = func.nullif(func.btrim(func.substr(written, comma + 1)), "")
    family = func.btrim(func.split_part(written, ",", 1))
    return case((comma > 0, func.concat_ws(" ", given, family)), else_=written)


Author.written = column_property(  # ty: ignore[invalid-assignment]
    select(Authorship.written)
    .where(Authorship.author_id == Author.id)
    .order_by(
        (_given_family(Authorship.written) == Author.name).desc(), Authorship.written
    )
    .limit(1)
    .correlate_except(Authorship)
    .scalar_subquery()
)


class AuthorsApart(Base):
    """Two people with the same name, said to be different (after a split):
    matching by name never joins them again. ``first`` < ``second``."""

    __tablename__ = "authors_apart"

    first: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True
    )
    second: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True
    )


class AuthorChangeKind(StrEnum):
    SPLIT = "split"
    """Papers went to a new person of the same name (``other_id``)."""
    MERGE = "merge"
    """The other person's papers came to this one; the other is gone."""
    APART = "apart"
    """Two people said to be different."""


class AuthorChange(Record, Base):
    """A fix by hand of who is who, so it can be traced and undone (author
    records are shared by everyone). See ``paperus.authors``."""

    __tablename__ = "author_changes"

    kind: Mapped[str] = mapped_column(String(16))
    """An ``AuthorChangeKind``."""
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(index=True)
    """The person split, kept or said to be different (no foreign key: the
    log outlives them)."""
    other_id: Mapped[uuid.UUID] = mapped_column(index=True)
    other_name: Mapped[str]
    moved: Mapped[list[list[str]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    """The papers' authors that changed person: [item id, position]."""
    renamed_from: Mapped[str | None]
    """A merge: the kept person's name before, if the merge changed it."""
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ItemView(Base):
    """When a person last opened an item (for their recent papers), and
    where they stopped reading it."""

    __tablename__ = "item_views"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reading: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """Where they stopped (``api.items.Reading``: the file, its page, the
    place on it), to go on from there in either view."""
    change: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0"), index=True
    )
    """Change number of the last open or reading position (``paperus.changes``)."""


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
    ocr_status: Mapped[str | None] = mapped_column(String(16), index=True)
    cover_pages: Mapped[list[int]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    """Pages (from 1) a site put in front of or behind the paper
    (``paperus.covers``): left out of its text; the viewer starts after."""
    file_marks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    """The PDF's own annotations taken in as ``Annotation`` rows (of the
    person who uploaded it): where each sits in the PDF ({page_index,
    rect}), so pages are drawn without them. None: not read yet."""

    version: Mapped[Version] = relationship(back_populates="files")
    blob: Mapped[Blob] = relationship(lazy="joined", innerjoin=True)


class OcrPage(Base):
    """The text OCR read on one page of a file's contents (images: page 0),
    kept so files are read again without OCR."""

    __tablename__ = "ocr_pages"

    blob_sha256: Mapped[bytes] = mapped_column(
        ForeignKey("blobs.sha256", ondelete="CASCADE"), primary_key=True
    )
    page: Mapped[int] = mapped_column(primary_key=True)
    """From 0."""
    text: Mapped[str] = mapped_column(Text)
    # A plain default: ``text()`` is hidden by the column above.
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    """Each line's text, confidence and box (left, top, right, bottom, in
    pixels of the image that was read)."""
    width: Mapped[int]
    height: Mapped[int]
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PageLayouts(Base):
    """Fluent mode's pieces of each page of a PDF's contents
    (``paperus.page_layout``), worked out once by the worker."""

    __tablename__ = "page_layouts"

    blob_sha256: Mapped[bytes] = mapped_column(
        ForeignKey("blobs.sha256", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int]
    """``page_layout.VERSION`` of the code that made them: older ones are
    made again."""
    pages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    """Per page: its size (points), whether it is set in two columns, its
    pieces in reading order. Empty: the PDF could not be read."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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


class LogEntry(Base):
    """One line of the log, from the server, the worker or someone's browser
    extension (``paperus.logbook``; Administration → Logs)."""

    __tablename__ = "log_entries"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    level: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(16))
    """"server", "worker" or "extension"."""
    logger: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    """Who reported it (the extension's entries)."""
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """E.g. the page the extension was on."""


class Notification(Base):
    """Something that happened that concerns a person (``paperus.notifications``):
    papers added to one of their groups, a published version found, a zip
    of their export written."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    """"added", "published", "erratum", "joined", "export", "export_failed"
    or "import"."""
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    """What to say: the paper, the group, who, how many; the export and
    which part."""
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """A smart collection: it holds the papers matching these rules
    (``organize.Rules``) instead of papers added to it."""
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


class Note(Record, Trashable, Base):
    """A person's writing about sources, in Markdown (see docs/architecture.md).

    Owned like items, linked to any number of items (none: a standalone
    note), held by collections like items. No versions: each save keeps the
    previous text in ``NoteRevision``.
    """

    __tablename__ = "notes"

    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("libraries.id", ondelete="RESTRICT"), index=True
    )
    """The owner: a person's or a group's library."""
    text: Mapped[str] = mapped_column(server_default="")
    title: Mapped[str] = mapped_column(String(300), server_default="")
    """The first line without Markdown marks, cached for lists."""
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    change: Mapped[int] = mapped_column(BigInteger, index=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    text_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    """When the text last changed (for the edit history)."""

    item_links: Mapped[list[NoteItem]] = relationship(
        back_populates="note",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="NoteItem.created_at",
    )
    collection_links: Mapped[list[CollectionNote]] = relationship(
        back_populates="note", cascade="all, delete-orphan", lazy="selectin"
    )


class NoteItem(Base):
    """A note is about an item, optionally at a page."""

    __tablename__ = "note_items"

    note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    page: Mapped[int | None]
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    note: Mapped[Note] = relationship(back_populates="item_links")
    item: Mapped[Item] = relationship(lazy="joined", innerjoin=True)


class CollectionNote(Base):
    __tablename__ = "collection_notes"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    note: Mapped[Note] = relationship(back_populates="collection_links")
    collection: Mapped[Collection] = relationship(lazy="joined", innerjoin=True)


class NoteRevision(Record, Base):
    """An earlier text of a note, kept when it was replaced."""

    __tablename__ = "note_revisions"

    note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str]
    written_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    written_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    """When this text was last saved, before it was replaced."""


class NoteChunk(Base):
    """A note's text as search passages, in order (like ``FileChunk``)."""

    __tablename__ = "note_chunks"

    note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_sha256: Mapped[bytes] = mapped_column(ForeignKey("chunks.sha256"), index=True)


class ItemChunk(Base):
    """A paper's details (its title and abstract) as one search passage, so
    that search finds it by them, with or without a file, and ranks such a
    match higher. Kept current on every change (``paperus.details``)."""

    __tablename__ = "item_chunks"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_sha256: Mapped[bytes] = mapped_column(ForeignKey("chunks.sha256"), index=True)


class ImportStatus(StrEnum):
    RECEIVING = "receiving"
    """A folder being uploaded file by file (``api.imports``); its files are
    the import's parts, by their path in the folder."""
    NEEDS_CHOICES = "needs_choices"
    """A paperus export: waiting for the person to choose where each of its
    owners goes (``Import.choices``)."""
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Import(Record, Base):
    """An import from another reference manager, run by the worker."""

    __tablename__ = "imports"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE")
    )
    """Who owns what the import adds."""
    filename: Mapped[str] = mapped_column(String(255))
    blob_sha256: Mapped[bytes | None] = mapped_column(
        ForeignKey("blobs.sha256", ondelete="SET NULL")
    )
    """The uploaded file (dropped from the import when done)."""
    format: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    done: Mapped[int] = mapped_column(server_default=text("0"))
    total: Mapped[int] = mapped_column(server_default=text("0"))
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None]
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    choices: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """A paperus export: its owners and parts, and where the person chose
    each owner to go (``api.imports.ImportChoices``)."""

    parts: Mapped[list[ImportPart]] = relationship(
        cascade="all, delete-orphan", order_by="ImportPart.position"
    )
    """Further uploaded files (the other parts of a paperus export)."""


class ImportPart(Base):
    """Another uploaded file of an import (a paperus export in several
    zips); dropped with the upload when the import is done."""

    __tablename__ = "import_parts"

    import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("imports.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    blob_sha256: Mapped[bytes | None] = mapped_column(
        ForeignKey("blobs.sha256", ondelete="SET NULL"), index=True
    )


class ExportStatus(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    EXPIRED = "expired"
    """Its zips were deleted after a day (``paperus.export.KEEP``)."""


class Export(Record, Base):
    """A person's export of what they can see (see ``paperus.export``): zips
    written by the worker, kept for a day."""

    __tablename__ = "exports"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16))
    options: Mapped[dict[str, Any]] = mapped_column(JSONB)
    """What to export (``export.Options``)."""
    done: Mapped[int] = mapped_column(server_default=text("0"))
    total: Mapped[int] = mapped_column(server_default=text("0"))
    size: Mapped[int | None] = mapped_column(BigInteger)
    """Bytes of all its zips together."""
    parts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    """Its zips, in order: name and size of each, as each is written."""
    error: Mapped[str | None]
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotDuplicate(Base):
    """Two papers someone said are different, though they look alike; they
    are not suggested as duplicates again. ``item_a`` < ``item_b``."""

    __tablename__ = "not_duplicates"

    item_a: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    item_b: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Favourite(Base):
    """A paper a person starred (each person their own)."""

    __tablename__ = "favourites"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PinnedCollection(Base):
    """A collection a person pinned to their sidebar."""

    __tablename__ = "pinned_collections"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AnnotationKind(StrEnum):
    """As PDF annotations (Zotero's kinds, plus strike-through)."""

    HIGHLIGHT = "highlight"
    """Highlight: text marked (``rects``)."""
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"
    NOTE = "note"
    """Text (a sticky note): a spot (``rects``: one small square)."""
    TEXT = "text"
    """FreeText: words written on the page (``rects``, ``font_size``)."""
    IMAGE = "image"
    """Square: an area, e.g. a figure or an equation (``rects``: one)."""
    INK = "ink"
    """Ink: drawn by hand (``paths``, ``width``)."""


class Annotation(Record, Base):
    """A person's mark on a file's page: where (PDF points from the page's
    lower left, as in PDF annotations: ``rects`` [x1, y1, x2, y2], or
    ``paths`` [x, y, x, y, …] with a ``width``), its colour, the text it
    marks, a comment and tags. Seen by its person, and by those who may
    read the paper if the person shares their annotations of it
    (``AnnotationShare``). See ``paperus.annotations``."""

    __tablename__ = "annotations"

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    """An ``AnnotationKind``."""
    page_index: Mapped[int]
    """From 0."""
    page_label: Mapped[str | None] = mapped_column(String(32))
    """As the PDF numbers its pages ("iv", "12"), if it does."""
    position: Mapped[dict[str, Any]] = mapped_column(JSONB)
    color: Mapped[str] = mapped_column(String(7))
    """"#ffd400"."""
    tags: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    imported: Mapped[bool] = mapped_column(server_default=text("false"))
    """Taken in from the PDF itself."""
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    change: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0"), index=True
    )
    """Change number of the last change (``paperus.changes``)."""
    # Named like SQLAlchemy's text(): after the defaults that use it.
    text: Mapped[str | None] = mapped_column(Text)
    """The text marked, or written (``text``)."""
    comment: Mapped[str | None] = mapped_column(Text)


class AnnotationShare(Base):
    """A person shows their annotations of a paper to everyone who may read
    it (its group)."""

    __tablename__ = "annotation_shares"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True, index=True
    )
