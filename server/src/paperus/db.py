"""Database engine and sessions."""

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    # Hooks on every session: change numbers, papers' details for search,
    # notifications of papers added to groups, arXiv's versions of files.
    from paperus import arxiv_versions, changes, details, notifications  # noqa: F401

    return sessionmaker(engine, expire_on_commit=False)


def check_connection(engine: Engine) -> None:
    """Raise if the database cannot be reached."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
