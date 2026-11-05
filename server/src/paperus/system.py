"""Settings that admins change at runtime (the design: settings in the web
UI, not config files). Environment variables (``paperus.config``) give the
defaults; values saved here override them.
"""

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus.config import Settings
from paperus.models import SystemSetting

KEY = "config"


class SystemConfig(BaseModel):
    embedding_model: str
    """Model for search by meaning; a change re-embeds in the background."""


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
