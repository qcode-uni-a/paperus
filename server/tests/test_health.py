from fastapi.testclient import TestClient

from paperus.app import create_app
from paperus.config import Settings

UNREACHABLE_DB = "postgresql+psycopg://paperus:paperus@127.0.0.1:1/paperus"


def test_health() -> None:
    client = TestClient(create_app(Settings(database_url=UNREACHABLE_DB)))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_db(client: TestClient) -> None:
    response = client.get("/api/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_db_unreachable() -> None:
    client = TestClient(create_app(Settings(database_url=UNREACHABLE_DB)))
    response = client.get("/api/health/db")
    assert response.status_code == 503
