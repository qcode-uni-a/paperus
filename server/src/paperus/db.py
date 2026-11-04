"""Database engine."""

from sqlalchemy import Engine, create_engine, text


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def check_connection(engine: Engine) -> None:
    """Raise if the database cannot be reached."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
