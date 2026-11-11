"""Settings that admins change at runtime (the design: settings in the web
UI, not config files). Environment variables (``paperus.config``) give the
defaults; values saved here override them.
"""

import logging
import uuid
from typing import Any, Literal, Self

import httpx2
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import readable
from paperus.config import Settings
from paperus.metadata import user_agent
from paperus.models import SystemSetting

KEY = "config"

DateFormat = Literal["browser", "europe", "uk", "iso", "us"]


class Joining(BaseModel):
    group_id: uuid.UUID
    role: Literal["reader", "member"] = "member"


class SystemConfig(BaseModel):
    embedding_model: str
    """Model for search by meaning; a change re-embeds in the background.
    The ML service keeps it loaded."""
    ml_threads: int | None = Field(None, ge=0, le=1024)
    """CPU threads the ML service uses per model; 0: all it sees; None: the
    ML service's own setting (``PAPERUS_ML_INTRA_OP_THREADS``)."""
    rerank: Literal["auto", "on", "off"] = "auto"
    """Reorder the best search hits with a reranker (better first hits):
    "auto" when the ML service runs on a GPU, as on a CPU it takes seconds
    per search."""
    rerank_model: str = "bge-reranker-v2-m3"
    ocr: bool = True
    """Read the text of scanned pages and images (OCR), in the background:
    a few seconds per page on a CPU."""
    ocr_model: str = "pp-ocrv6-small"

    # Server
    public_url: HttpUrl | None = None
    """The address people use (behind a proxy), for links the server makes,
    e.g. for AI assistants; by default the address a request came to."""
    contact_email: str | None = Field(
        None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+$"
    )
    """Sent to Crossref and other metadata services, which ask for one."""
    find_published: bool = True
    """Look for the published versions of preprints (by their arXiv IDs, at
    arXiv and OpenAlex) and add those found; a few dozen papers an hour."""
    find_references: bool = True
    """Look for papers' reference lists (arXiv's LaTeX sources, Crossref,
    the PDF's own list); a few dozen papers an hour."""
    find_authors: bool = True
    """Look up papers' authors at OpenAlex by the papers' DOIs: their ids,
    ORCID iDs and affiliations on each paper (``paperus.authors``); a few
    hundred papers an hour."""
    open_access_auto: bool = False
    """Papers added without a file get an open-access copy by themselves, in
    the background: their arXiv version (found via OpenAlex), else one
    Unpaywall knows (needs the contact email). Sends their DOIs there."""
    max_upload_mb: int | None = Field(None, ge=1, le=100_000)
    """Largest file one may upload (an import's files each)."""
    date_format: DateFormat = "browser"
    """How the website shows dates and times, for everyone: "browser" (each
    browser's own), "europe" (31.12.2026, 14:30), "uk" (31/12/2026, 14:30),
    "iso" (2026-12-31, 14:30) or "us" (12/31/2026, 2:30 PM)."""

    # Trash
    trash_days: int | None = Field(None, ge=1, le=3650)
    """Papers, files and notes in the trash are deleted for good after this
    many days; None: they stay until emptied by hand."""

    # Logging
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    # Background jobs
    jobs_text: int = Field(2, ge=1, le=16)
    """Files read at the same time (each takes a CPU core)."""
    jobs_ml: int = Field(1, ge=1, le=8)
    """Files sent to the ML service at the same time."""
    jobs_import: int = Field(1, ge=1, le=4)
    """Imports at the same time (one owner's run one after another)."""
    night_hour: int = Field(2, ge=0, le=23)
    """Hour (UTC) of the nightly jobs: emptying the trash, the integrity
    check."""
    integrity_schedule: Literal["off", "daily", "weekly"] = "weekly"
    """How often the integrity check runs (weekly: on Sundays)."""

    # Authentication
    session_days: int = Field(30, ge=1, le=365)
    """How long one stays logged in on a device."""
    password_min_length: int = Field(8, ge=8, le=128)
    password_login: bool = True
    """Off: only administrators log in with a password (a way in when the
    OIDC login fails); everyone else uses the OIDC login."""
    oidc_enabled: bool = False
    """Login with OpenID Connect (OIDC) (see ``paperus.oidc``)."""
    oidc_issuer: str | None = Field(None, max_length=500, pattern=r"^https?://\S+$")
    """The identity provider's address, e.g.
    https://login.uni-example.de/realms/staff (its discovery document is at
    ``/.well-known/openid-configuration`` below it)."""
    oidc_client_id: str | None = Field(None, max_length=200)
    oidc_label: str = Field("Log in with OIDC", min_length=1, max_length=60)
    """The login button's text."""
    oidc_username_claim: str = Field(
        "preferred_username", pattern=r"^[A-Za-z0-9_:.-]{1,60}$"
    )
    """The claim that becomes the username (e.g. preferred_username, email);
    an existing account of that name is linked on its first login."""
    oidc_create_accounts: bool = True
    """Create an account on someone's first OIDC login; off: only
    people an administrator added beforehand."""

    # Readable copy (storage template)
    copy_enabled: bool = False
    """Keep a readable copy of the library on disk (``paperus.readable``),
    in the folder ``PAPERUS_COPY_PATH``."""
    copy_template: str = Field(readable.DEFAULT_TEMPLATE, min_length=1, max_length=300)
    """Where each file goes; ``/`` makes folders."""
    copy_links: bool = False
    """Hard links instead of copies: no extra space, but the copy's files are
    the stored ones (editing one changes the library's)."""

    # Users
    new_user_groups: list[Joining] = Field(default_factory=list, max_length=20)
    """Groups new accounts join (made by an administrator or on a first
    OIDC login)."""

    @field_validator("copy_template")
    @classmethod
    def _known_variables(cls, template: str) -> str:
        return readable.check_template(template)

    @model_validator(mode="after")
    def _login_possible(self) -> Self:
        if self.oidc_enabled and not (self.oidc_issuer and self.oidc_client_id):
            raise ValueError("the OIDC login needs an issuer and a client ID")
        if not self.password_login and not self.oidc_enabled:
            raise ValueError("password login can only be off with OIDC login")
        return self


# Defaults from the environment: an unset value here falls back to them.
_FROM_ENVIRONMENT = ("contact_email", "max_upload_mb")


def defaults(settings: Settings) -> SystemConfig:
    return SystemConfig(
        embedding_model=settings.embedding_model,
        contact_email=settings.contact_email,
        max_upload_mb=max(1, settings.max_upload_bytes // 2**20),
    )


def load_config(db: Session, settings: Settings) -> SystemConfig:
    row = db.get(SystemSetting, KEY)
    saved = dict(row.value) if row else {}
    for name in _FROM_ENVIRONMENT:
        if saved.get(name) is None:
            saved.pop(name, None)
    base = defaults(settings).model_dump()
    return SystemConfig.model_validate({**base, **saved})


def max_upload_bytes(db: Session, settings: Settings) -> int:
    """The limit set in the administration, else the environment's (exact)."""
    row = db.get(SystemSetting, KEY)
    chosen = (row.value if row else {}).get("max_upload_mb")
    return int(chosen) * 2**20 if chosen else settings.max_upload_bytes


def _save(db: Session, key: str, value: dict[str, Any]) -> None:
    db.execute(
        insert(SystemSetting)
        .values(key=key, value=value)
        .on_conflict_do_update(index_elements=["key"], set_={"value": value})
    )


def save_config(db: Session, config: SystemConfig) -> None:
    _save(db, KEY, config.model_dump(mode="json"))


INSTALLATION_KEY = "installation"


def installation_id(db: Session) -> str:
    """This library's own id, made once: it names the folder of stored files
    the library owns (``storage.owns``). Commits when it makes it."""
    row = db.get(SystemSetting, INSTALLATION_KEY)
    if row is None:
        db.execute(
            insert(SystemSetting)
            .values(key=INSTALLATION_KEY, value={"id": str(uuid.uuid4())})
            .on_conflict_do_nothing()
        )
        db.commit()
        row = db.get_one(SystemSetting, INSTALLATION_KEY)
    return str(row.value["id"])


OIDC_SECRET_KEY = "oidc_secret"


def oidc_secret(db: Session, settings: Settings) -> str | None:
    """The OIDC login's client secret: from the environment
    (``PAPERUS_OIDC_CLIENT_SECRET``) or set in the administration. Kept apart
    from the settings, so it is never sent to the website."""
    if settings.oidc_client_secret:
        return settings.oidc_client_secret
    row = db.get(SystemSetting, OIDC_SECRET_KEY)
    return str(row.value["secret"]) if row and row.value.get("secret") else None


def save_oidc_secret(db: Session, secret: str | None) -> None:
    _save(db, OIDC_SECRET_KEY, {"secret": secret})


VECTORS_KEY = "vectors"


def vectors_in_use(db: Session, model: str) -> str:
    """What the model's vectors are stored as, as the ML service last said:
    the model's name, or with the variant of its model file (``…@fp16`` on a
    GPU). For figures; embedding and search ask the ML service."""
    row = db.get(SystemSetting, VECTORS_KEY)
    known = row.value.get(model) if row else None
    return str(known) if known else model


def save_vectors_in_use(db: Session, model: str, vectors: str) -> None:
    row = db.get(SystemSetting, VECTORS_KEY)
    _save(db, VECTORS_KEY, {**(row.value if row else {}), model: vectors})


BACKUPS_KEY = "backups"


class BackupConfig(BaseModel):
    """When backups run on their own (checked every hour by the worker)."""

    schedule: Literal["off", "daily", "weekly"] = "daily"
    """Weekly backups run on Mondays. Daily from the start, so a new server
    is never without one."""
    hour: int = Field(3, ge=0, le=23)
    """At which hour (UTC)."""
    with_files: bool = False
    """Also back up the files (only new ones are copied each time); by
    default the database only, which is small."""
    keep: int = Field(7, ge=1, le=365)
    """How many backups to keep; older ones are removed."""


def load_backup_config(db: Session) -> BackupConfig:
    saved = db.get(SystemSetting, BACKUPS_KEY)
    return BackupConfig.model_validate(saved.value if saved else {})


def save_backup_config(db: Session, config: BackupConfig) -> None:
    _save(db, BACKUPS_KEY, config.model_dump())


def apply(config: SystemConfig, http: httpx2.Client) -> None:
    """Settings that act inside a running process (server or worker): the
    log level and the contact sent to metadata services."""
    level = getattr(logging, config.log_level.upper())
    logging.getLogger("paperus").setLevel(level)
    http.headers["User-Agent"] = user_agent(config.contact_email)
