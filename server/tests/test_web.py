from pathlib import Path

from fastapi.testclient import TestClient

from paperus.app import create_app
from paperus.config import Settings

UNREACHABLE_DB = "postgresql+psycopg://paperus:paperus@127.0.0.1:1/paperus"


def make_site(root: Path) -> None:
    (root / "_app" / "immutable").mkdir(parents=True)
    (root / "_app" / "immutable" / "app.js").write_text("console.log(1)")
    (root / "200.html").write_text("<html>app</html>")
    (root / "robots.txt").write_text("User-agent: *")


def test_serves_the_website(tmp_path: Path) -> None:
    make_site(tmp_path)
    client = TestClient(
        create_app(Settings(database_url=UNREACHABLE_DB, web_path=tmp_path))
    )
    assert client.get("/").text == "<html>app</html>"
    assert client.get("/items/123").text == "<html>app</html>"
    assert client.get("/robots.txt").text == "User-agent: *"
    assert client.get("/_app/immutable/app.js").text == "console.log(1)"
    assert client.get("/../pyproject.toml").text == "<html>app</html>"
    assert client.get("/api/unknown").status_code == 404
    assert client.get("/api/health").json() == {"status": "ok"}


def test_without_website(tmp_path: Path) -> None:
    client = TestClient(
        create_app(Settings(database_url=UNREACHABLE_DB, web_path=tmp_path))
    )
    assert client.get("/").status_code == 404
