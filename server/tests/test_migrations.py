"""Data migrations that need checking with data in place."""

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import SERVER_DIR


def test_installations_using_bge_m3_keep_it(
    engine: Engine, db: Session, database_url: str
) -> None:
    config = Config(SERVER_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "0014")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM system_settings"))
        connection.execute(
            text("INSERT INTO chunks (sha256, text) VALUES ('\\x00', 'rain')")
        )
        connection.execute(
            text(
                "INSERT INTO embeddings (chunk_sha256, model, embedding)"
                " VALUES ('\\x00', 'bge-m3', '[1,0]')"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        value = connection.scalar(
            text("SELECT value FROM system_settings WHERE key = 'config'")
        )
    assert value == {"embedding_model": "bge-m3"}
    # Without bge-m3 vectors (a new installation): nothing saved, the
    # default applies.
    command.downgrade(config, "0014")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM system_settings"))
        connection.execute(text("DELETE FROM embeddings"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM system_settings")) == 0
