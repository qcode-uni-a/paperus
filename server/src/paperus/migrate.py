"""Bring the database schema up to date (``paperus migrate``)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from paperus.config import Settings

# server/alembic.ini, next to the migrations (also inside the container image).
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def migrate(settings: Settings) -> None:
    config = Config(ALEMBIC_INI)
    # "%" is interpolation syntax in Alembic's config; passwords may contain it.
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")
