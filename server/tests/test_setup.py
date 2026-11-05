"""First start: a new administrator, or a backup restored."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from paperus.backup import create_backup
from paperus.config import Settings
from paperus.storage import BlobStore


def test_start_new(client: TestClient) -> None:
    state = client.get("/api/setup").json()
    assert state["needed"] is True
    assert state["backups"] == []
    assert client.get("/api/auth/me").status_code == 401
    created = client.post(
        "/api/setup/admin", json={"username": "boss", "password": "long enough"}
    )
    assert created.status_code == 201
    me = client.get("/api/auth/me").json()  # logged in by the cookie
    assert (me["username"], me["is_admin"]) == ("boss", True)
    # Once someone exists, setup is over.
    assert client.get("/api/setup").json() == {
        "needed": False,
        "backup_path": None,
        "backups": [],
    }
    again = client.post(
        "/api/setup/admin", json={"username": "intruder", "password": "long enough"}
    )
    assert again.status_code == 409
    assert client.post("/api/setup/restore", json={"name": "x"}).status_code == 409


def test_restore_on_first_start(
    logged_in: TestClient, engine: Engine, blobs: BlobStore, settings: Settings
) -> None:
    logged_in.post("/api/items", json={"metadata": {"title": "From the old server"}})
    manifest = create_backup(engine, blobs, settings.backup_path, with_files=True)
    # A new, empty installation that has the backup folder.
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE users, items, libraries CASCADE"))
    logged_in.cookies.clear()
    state = logged_in.get("/api/setup").json()
    assert [b["name"] for b in state["backups"]] == [manifest.name]
    assert state["backups"][0]["items"] == 1

    missing = logged_in.post("/api/setup/restore", json={"name": "nope"})
    assert missing.status_code == 409
    restored = logged_in.post("/api/setup/restore", json={"name": manifest.name})
    assert restored.status_code == 204
    assert logged_in.get("/api/setup").json()["needed"] is False
    login = logged_in.post(
        "/api/auth/login", json={"username": "ada", "password": "secret"}
    )
    assert login.status_code == 200
    titles = [i["title"] for i in logged_in.get("/api/items").json()]
    assert titles == ["From the old server"]
