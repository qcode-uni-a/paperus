"""Settings that admins change at runtime (the design: settings in the web
UI, not config files). Environment variables (``paperus.config``) give the
defaults; values saved here override them.
"""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus.config import Settings
from paperus.models import SystemSetting

KEY = "config"


class SystemConfig(BaseModel):
    embedding_model: str
    """Model for search by meaning; a change re-embeds in the background.
    The ML service keeps it loaded."""
    ml_threads: int | None = Field(None, ge=0, le=1024)
    """CPU threads the ML service uses per model; 0: all it sees; None: the
    ML service's own setting (``PAPERUS_ML_INTRA_OP_THREADS``)."""


def defaults(settings: Settings) -> SystemConfig:
    return SystemConfig(embedding_model=settings.embedding_model)


def load_config(db: Session, settings: Settings) -> SystemConfig:
    saved = db.get(SystemSetting, KEY)
    base = defaults(settings).model_dump()
    return SystemConfig.model_validate({**base, **(saved.value if saved else {})})


def save_config(db: Session, config: SystemConfig) -> None:
    value = config.model_dump()
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
