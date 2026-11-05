"""Prometheus metrics: requests, searches and the library's figures."""

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest
from sqlalchemy.orm import Session, sessionmaker

from paperus.config import Settings
from paperus.metrics import LibraryCollector
from tests.people import Person


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
