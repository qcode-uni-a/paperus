"""Prometheus metrics: requests, searches and the library's figures."""

import socket

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App, PsycopgConnector
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from paperus import metrics
from paperus.app import create_app
from paperus.backup import create_backup
from paperus.config import Settings
from paperus.jobs import conninfo
from paperus.metrics import LibraryCollector
from paperus.storage import BlobStore
from tests.people import Person

UNREACHABLE_DB = "postgresql+psycopg://paperus:paperus@127.0.0.1:1/paperus"


def value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_requests_and_searches_are_counted(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    before = value(
        "paperus_http_requests_total",
        method="GET",
        route="/api/items/{item_id}",
        status="404",
    )
    searches = value("paperus_searches_total", mode="keyword")
    ada.get("/api/items/01900000-0000-7000-8000-000000000000")
    ada.get("/api/search", params={"q": "rain", "mode": "keyword"})
    assert (
        value(
            "paperus_http_requests_total",
            method="GET",
            route="/api/items/{item_id}",
            status="404",
        )
        == before + 1
    )
    assert value("paperus_searches_total", mode="keyword") == searches + 1


def test_library_figures(client: TestClient, db: Session, settings: Settings) -> None:
    ada = Person(client, db, "ada")
    ada.add("A paper")
    gone = ada.add("Gone")
    ada.delete(f"/api/items/{gone['id']}")
    ada.note("A note")
    registry = CollectorRegistry()
    registry.register(LibraryCollector(sessionmaker(bind=db.get_bind()), settings))
    text = generate_latest(registry).decode()
    assert "paperus_items 1.0" in text
    assert "paperus_items_in_trash 1.0" in text
    assert "paperus_notes 1.0" in text
    assert "paperus_users 1.0" in text
    assert 'paperus_embedded_chunks{model="bge-m3"} 0.0' in text


def test_jobs_and_backups(
    client: TestClient,
    db: Session,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
) -> None:
    jobs = App(connector=PsycopgConnector(conninfo=conninfo(settings.database_url)))
    with jobs.open():
        jobs.configure_task("paperus:extract_text", queue="text").defer(file_id="x")
    create_backup(engine, blobs, settings.backup_path, with_files=False)
    registry = CollectorRegistry()
    registry.register(LibraryCollector(sessionmaker(bind=engine), settings))
    text = generate_latest(registry).decode()
    assert 'paperus_jobs{queue="text",status="todo"} 1.0' in text
    assert "paperus_backups_bytes " in text
    assert "paperus_last_backup_timestamp_seconds " in text
    assert "paperus_disk_free_bytes " in text


def test_metrics_port_without_a_database(
    job_app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The requests are counted still; the library's figures are left out."""
    monkeypatch.setattr(metrics, "REGISTRY", CollectorRegistry())
    monkeypatch.setattr(metrics, "_started", False)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings = Settings(database_url=UNREACHABLE_DB, metrics_port=port)
    with TestClient(create_app(settings, job_app=job_app)):
        metrics.serve(port, sessionmaker(), settings)  # once only
        text = httpx2.get(f"http://127.0.0.1:{port}/metrics").text
    assert "paperus_items" not in text
