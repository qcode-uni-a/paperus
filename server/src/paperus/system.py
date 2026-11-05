"""Settings that admins change at runtime (the design: settings in the web
UI, not config files). Environment variables (``paperus.config``) give the
defaults; values saved here override them.
"""

import logging
from typing import Literal

import httpx2
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus.config import Settings
from paperus.metadata import user_agent
from paperus.models import SystemSetting

KEY = "config"


class SystemConfig(BaseModel):
    embedding_model: str
    """Model for search by meaning; a change re-embeds in the background.
    The ML service keeps it loaded."""
    ml_threads: int | None = Field(None, ge=0, le=1024)
    """CPU threads the ML service uses per model; 0: all it sees; None: the
    ML service's own setting (``PAPERUS_ML_INTRA_OP_THREADS``)."""

    # Server
    public_url: HttpUrl | None = None
    """The address people use (behind a proxy), for links the server makes,
    e.g. for AI assistants; by default the address a request came to."""
    contact_email: str | None = Field(
        None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+$"
    )
    """Sent to Crossref and other metadata services, which ask for one."""
    max_upload_mb: int | None = Field(None, ge=1, le=100_000)
    """Largest file one may upload (an import's files each)."""

    # Trash
    trash_days: int | None = Field(None, ge=1, le=3650)
    """Papers, files and notes in the trash are deleted for good after this
    many days; None: they stay until emptied by hand."""

    # Logging
    log_level: Literal["debug", "info", "warning", "error"] = "info"


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


def save_config(db: Session, config: SystemConfig) -> None:
    value = config.model_dump(mode="json")
    db.execute(
        insert(SystemSetting)
        .values(key=KEY, value=value)
        .on_conflict_do_update(index_elements=["key"], set_={"value": value})
    )


BACKUPS_KEY = "backups"


class BackupConfig(BaseModel):
    """When backups run on their own (checked every hour by the worker)."""

    schedule: Literal["off", "daily", "weekly"] = "off"
    """Weekly backups run on Mondays."""
    hour: int = Field(3, ge=0, le=23)
    """At which hour (UTC)."""
    with_files: bool = True
    """Also back up the files (only new ones are copied each time)."""
    keep: int = Field(7, ge=1, le=365)
    """How many backups to keep; older ones are removed."""


def load_backup_config(db: Session) -> BackupConfig:
    saved = db.get(SystemSetting, BACKUPS_KEY)
    return BackupConfig.model_validate(saved.value if saved else {})


def save_backup_config(db: Session, config: BackupConfig) -> None:
    value = config.model_dump()
    db.execute(
        insert(SystemSetting)
        .values(key=BACKUPS_KEY, value=value)
        .on_conflict_do_update(index_elements=["key"], set_={"value": value})
    )


def apply(config: SystemConfig, http: httpx2.Client) -> None:
    """Settings that act inside a running process (server or worker): the
    log level and the contact sent to metadata services."""
    level = getattr(logging, config.log_level.upper())
    logging.getLogger("paperus").setLevel(level)
    http.headers["User-Agent"] = user_agent(config.contact_email)
