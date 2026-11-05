"""Fixtures for tests that need Postgres.

They use the database ``paperus_test`` on the compose Postgres (override with
``PAPERUS_TEST_DATABASE_URL``). It is recreated once per test run and
emptied after each test. Without a reachable database these tests are skipped.
"""

import hashlib
import json
import math
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy import Engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from paperus.app import create_app
from paperus.auth import create_user
from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker
from paperus.jobs import tasks
from paperus.ml import MLClient
from paperus.storage import BlobStore, make_blob_store

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
                " AND tablename NOT IN ('alembic_version', 'change_counters')"
            )
        ).all()
        if tables:
            connection.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
        connection.execute(text("UPDATE change_counters SET value = 0"))


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


class FakeML:
    """Stands in for paperus-ml: a word's vector depends on its meaning group,
    so "gaps" and "missing" are close without sharing letters."""

    DIMENSIONS = 16
    SAME_MEANING: ClassVar[dict[str, str]] = {
        "gaps": "missing",
        "absent": "missing",
        "rainfall": "rain",
    }

    def __init__(self) -> None:
        self.down = False
        self.requests: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.config: dict[str, Any] = {"threads": 0, "keep": []}

    def vector(self, text: str) -> list[float]:
        vector = [0.0] * self.DIMENSIONS
        for word in re.findall(r"\w+", text.lower()):
            word = self.SAME_MEANING.get(word, word)
            vector[
                int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.DIMENSIONS
            ] += 1
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    MODELS: ClassVar[list[str]] = ["bge-m3", "multilingual-e5-small"]

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("ML service down")
        if request.url.path == "/ping":
            return httpx2.Response(200, json="pong")
        if request.url.path == "/config":
            if request.method == "PUT":
                self.config = json.loads(request.content)
            return httpx2.Response(200, json={**self.config, "cores": 8, "loaded": []})
        if request.url.path.endswith("/speed"):
            name = request.url.path.split("/")[2]
            if name not in self.MODELS:
                return httpx2.Response(404)
            return httpx2.Response(
                200,
                json={
                    "model": name,
                    "passages": 48,
                    "seconds": 6.0,
                    "passages_per_second": 8.0,
                    "load_seconds": 0.0,
                },
            )
        if request.url.path == "/models":
            models = [
                {
                    "name": name,
                    "task": "embedding",
                    "dimensions": self.DIMENSIONS,
                    "max_tokens": 512,
                    "loaded": False,
                    "cached_bytes": None,
                }
                for name in self.MODELS
            ]
            return httpx2.Response(200, json=models)
        if request.method == "DELETE":
            self.deleted.append(request.url.path.rsplit("/", 1)[1])
            return httpx2.Response(204)
        body = json.loads(request.content)
        if body.get("model") not in self.MODELS:
            return httpx2.Response(404, json={"detail": "unknown model"})
        self.requests.append(body)
        vectors = [self.vector(t) for t in body["texts"]]
        return httpx2.Response(
            200,
            json={
                "model": body["model"],
                "dimensions": self.DIMENSIONS,
                "embeddings": vectors,
            },
        )

    def client(self) -> MLClient:
        transport = httpx2.MockTransport(self)
        return MLClient(["http://ml"], http=httpx2.Client(transport=transport))


@pytest.fixture
def fake_ml() -> FakeML:
    return FakeML()


@pytest.fixture
def doi_registry() -> FakeDOIRegistry:
    return FakeDOIRegistry()


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return Settings(
        database_url=database_url,
        # The tests were written for it (the default is arctic-embed-m-v2).
        embedding_model="bge-m3",
        storage_path=tmp_path / "files",
        backup_path=tmp_path / "backups",
    )


@pytest.fixture
def job_app() -> App:
    """Jobs are recorded in memory; tests run them with ``process_file``."""
    app = App(connector=InMemoryConnector())
    app.add_tasks_from(tasks, namespace="paperus")
    return app


@pytest.fixture
def blobs(settings: Settings) -> BlobStore:
    return make_blob_store(settings)


@pytest.fixture
def client(
    settings: Settings,
    db: Session,
    doi_registry: FakeDOIRegistry,
    job_app: App,
    fake_ml: FakeML,
) -> Iterator[TestClient]:
    app = create_app(
        settings,
        http_client=httpx2.Client(transport=httpx2.MockTransport(doi_registry)),
        job_app=job_app,
        ml_client=fake_ml.client(),
    )
    # https, so the client sends the Secure session cookie back.
    with TestClient(app, base_url="https://testserver") as client:
        yield client


@pytest.fixture
def admin(client: TestClient, db: Session) -> TestClient:
    create_user(db, "root", "secret", is_admin=True)
    db.commit()
    response = client.post(
        "/api/auth/login", json={"username": "root", "password": "secret"}
    )
    assert response.status_code == 200
    return client


@pytest.fixture
def logged_in(client: TestClient, db: Session) -> TestClient:
    create_user(db, "ada", "secret")
    db.commit()
    response = client.post(
        "/api/auth/login", json={"username": "ada", "password": "secret"}
    )
    assert response.status_code == 200
    return client
