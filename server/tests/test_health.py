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


def test_extensions_may_ask_first() -> None:
    """The browser extension's preflight is answered (an access token, no
    cookies); a website's is not."""
    client = TestClient(create_app(Settings(database_url=UNREACHABLE_DB)))
    ask = {
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    }
    for origin in ("moz-extension://4f0c-11ab", "chrome-extension://abcdefgh"):
        response = client.options("/api/libraries", headers={"Origin": origin, **ask})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert "access-control-allow-credentials" not in response.headers
    response = client.options(
        "/api/libraries", headers={"Origin": "https://elsewhere.example", **ask}
    )
    assert "access-control-allow-origin" not in response.headers
