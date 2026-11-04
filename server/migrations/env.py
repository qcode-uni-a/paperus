"""Alembic environment: the database URL comes from paperus settings."""

from logging.config import fileConfig

from alembic import context

from paperus.config import Settings
from paperus.db import make_engine
from paperus.models import Base

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Leave Procrastinate's tables to its own schema file."""
    return not (name or "").startswith("procrastinate")


def database_url() -> str:
    """Tests pass the URL in the Alembic config; otherwise use the settings."""
    return context.config.get_main_option("sqlalchemy.url") or Settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(), target_metadata=target_metadata, include_name=include_name
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(database_url())
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                include_name=include_name,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
