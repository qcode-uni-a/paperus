"""Fixtures for tests that need Postgres.

They use the database ``paperus_test`` on the compose Postgres (override with
``PAPERUS_TEST_DATABASE_URL``). It is recreated once per test run and
emptied after each test. Without a reachable database these tests are skipped.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from paperus.app import create_app
from paperus.auth import create_user
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
    )
    try:
        with admin.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
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


class FakeDOIRegistry:
    """Stands in for doi.org: answers with the CSL-JSON in ``records``."""

    def __init__(self) -> None:
        self.records: dict[str, Any] = {}
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        doi = request.url.path.removeprefix("/")
        if doi not in self.records:
            return httpx2.Response(404)
        return httpx2.Response(200, json=self.records[doi])


@pytest.fixture
def doi_registry() -> FakeDOIRegistry:
    return FakeDOIRegistry()


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return Settings(database_url=database_url, storage_path=tmp_path / "files")


@pytest.fixture
def client(
    settings: Settings, db: Session, doi_registry: FakeDOIRegistry
) -> Iterator[TestClient]:
    app = create_app(
        settings,
        http_client=httpx2.Client(transport=httpx2.MockTransport(doi_registry)),
    )
    # https, so the client sends the Secure session cookie back.
    with TestClient(app, base_url="https://testserver") as client:
        yield client


@pytest.fixture
def logged_in(client: TestClient, db: Session) -> TestClient:
    create_user(db, "ada", "secret")
    db.commit()
    response = client.post(
        "/api/auth/login", json={"username": "ada", "password": "secret"}
    )
    assert response.status_code == 200
    return client
