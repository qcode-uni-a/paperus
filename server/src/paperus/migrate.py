"""Bring the database schema up to date (``paperus migrate``)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from paperus.config import Settings

# Shipped inside the package, so this works from a wheel or the image.
MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def migrate(settings: Settings) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    # "%" is interpolation syntax in Alembic's config; passwords may contain it.
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")
