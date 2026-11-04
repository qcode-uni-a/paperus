"""Fixtures for tests that need Postgres.

They use the database ``paperus_test`` on the compose Postgres (override with
``PAPERUS_TEST_DATABASE_URL``). It is recreated once per test run and
emptied after each test. Without a reachable database these tests are skipped.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from paperus.app import create_app
from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "PAPERUS_TEST_DATABASE_URL",
    "postgresql+psycopg://paperus:paperus@localhost:5432/paperus_test",
)
SERVER_DIR = Path(__file__).parent.parent


def _recreate_database(url: str) -> None:
    test_url = make_url(url)
    admin = make_engine(
        test_url.set(database="postgres").render_as_string(hide_password=False)
    ).execution_options(isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            name = test_url.database
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    try:
        _recreate_database(TEST_DATABASE_URL)
    except OperationalError:
        pytest.skip("test database unreachable (start it with `docker compose up -d`)")
    config = Config(SERVER_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    engine = make_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with make_sessionmaker(engine)() as session:
        yield session
    with engine.begin() as connection:
        tables = connection.scalars(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                " AND tablename != 'alembic_version'"
            )
        ).all()
        if tables:
            connection.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))


@pytest.fixture
def client(database_url: str, db: Session) -> TestClient:
    # https, so the client sends the Secure session cookie back.
    return TestClient(
        create_app(Settings(database_url=database_url)), base_url="https://testserver"
    )
