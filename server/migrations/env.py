"""Alembic environment: the database URL comes from paperUs settings."""

from logging.config import fileConfig

from alembic import context

from paperus.config import Settings
from paperus.db import make_engine

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    context.configure(url=Settings().database_url, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(Settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
