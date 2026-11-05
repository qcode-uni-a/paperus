"""Backups: written from one snapshot, restored into an empty database."""

import gzip
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, make_url, text

from paperus.backup import (
    BackupError,
    check_restore,
    create_backup,
    delete_backup,
    due,
    list_backups,
    prune,
    restore_backup,
)
from paperus.config import Settings
from paperus.db import make_engine
from paperus.storage import BlobStore, FilesystemStore
from tests.conftest import _recreate_database

PDF = b"%PDF-1.7\n" + b"x" * 4000 + b"\n%%EOF\n"


@pytest.fixture
def restore_url(database_url: str) -> Iterator[str]:
    url = make_url(database_url).set(database="paperus_test_restore")
    rendered = url.render_as_string(hide_password=False)
    _recreate_database(rendered)
    yield rendered


def fill(client: TestClient) -> None:
    """Some of everything: a paper with a file and a tag, a collection."""
    item = client.post("/api/items", json={"metadata": {"title": "Kept safe"}}).json()
    client.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("paper.pdf", PDF, "application/pdf")},
    )
    client.post(f"/api/items/{item['id']}/tags", json={"name": "important"})
    shelf = client.post("/api/collections", json={"name": "Shelf"}).json()
    client.post(
        f"/api/collections/{shelf['id']}/items", json={"item_ids": [item["id"]]}
    )


def counts(engine: Engine) -> dict[str, int]:
    tables = [
        "users",
        "libraries",
        "items",
        "versions",
        "files",
        "blobs",
        "tags",
        "item_tags",
        "collections",
        "collection_items",
        "change_counters",
    ]
    with engine.connect() as connection:
        return {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            or 0
            for table in tables
        }


def test_backup_and_restore(
    logged_in: TestClient,
    engine: Engine,
    blobs: BlobStore,
    tmp_path: Path,
    restore_url: str,
) -> None:
    fill(logged_in)
    root = tmp_path / "backups"
    manifest = create_backup(engine, blobs, root, with_files=True)
    assert manifest.with_files and manifest.files == 1
    assert manifest.tables["items"].rows == 1
    assert [m.name for m in list_backups(root)] == [manifest.name]

    other_store = FilesystemStore(tmp_path / "restored-files")
    settings = Settings(
        database_url=restore_url, storage_path=tmp_path / "restored-files"
    )
    restored_engine = make_engine(restore_url)
    try:
        restore_backup(
            settings, restored_engine, other_store, root, manifest.name, replace=False
        )
        assert counts(restored_engine) == counts(engine)
        with restored_engine.connect() as connection:
            sha = connection.execute(text("SELECT sha256 FROM blobs")).scalar_one()
            title = connection.execute(text("SELECT title FROM items")).scalar_one()
            searchable = connection.execute(
                text("SELECT count(*) FROM chunks WHERE tsv IS NOT NULL")
            ).scalar_one()
            total = connection.execute(text("SELECT count(*) FROM chunks")).scalar_one()
        assert title == "Kept safe"
        assert searchable == total  # generated search columns are rebuilt
        assert other_store.exists(sha)

        # Not over a database in use, unless asked to replace it.
        with pytest.raises(BackupError, match="not empty"):
            restore_backup(
                settings,
                restored_engine,
                other_store,
                root,
                manifest.name,
                replace=False,
            )
        restore_backup(
            settings, restored_engine, other_store, root, manifest.name, replace=True
        )
        assert counts(restored_engine) == counts(engine)
    finally:
        restored_engine.dispose()


def test_refuses_damaged_and_newer_backups(
    logged_in: TestClient,
    engine: Engine,
    blobs: BlobStore,
    tmp_path: Path,
    restore_url: str,
) -> None:
    fill(logged_in)
    root = tmp_path / "backups"
    settings = Settings(database_url=restore_url, storage_path=tmp_path / "x")
    restored_engine = make_engine(restore_url)
    try:
        damaged = create_backup(engine, blobs, root, with_files=False)
        with gzip.open(root / damaged.name / "tables" / "items.tsv.gz", "ab") as out:
            out.write(b"tampered\n")
        with pytest.raises(BackupError, match="damaged"):
            restore_backup(
                settings, restored_engine, blobs, root, damaged.name, replace=False
            )

        manifest_path = root / damaged.name / "manifest.json"
        data = json.loads(manifest_path.read_text())
        data["revision"] = "9999"
        manifest_path.write_text(json.dumps(data))
        with pytest.raises(BackupError, match="newer paperus"):
            restore_backup(
                settings, restored_engine, blobs, root, damaged.name, replace=False
            )
    finally:
        restored_engine.dispose()


def test_files_are_shared_and_pruned(
    logged_in: TestClient, engine: Engine, blobs: BlobStore, tmp_path: Path
) -> None:
    fill(logged_in)
    root = tmp_path / "backups"
    first = create_backup(engine, blobs, root, with_files=True)
    # Names have whole seconds; the second backup needs its own.
    (root / first.name).rename(root / "2000-01-01T00-00-00Z")
    second = create_backup(engine, blobs, root, with_files=True)
    pool = [p for p in (root / "files").rglob("*") if p.is_file()]
    assert len(pool) == 1  # stored once for both backups
    assert prune(root, keep=1) == ["2000-01-01T00-00-00Z"]
    assert [m.name for m in list_backups(root)] == [second.name]
    assert len([p for p in (root / "files").rglob("*") if p.is_file()]) == 1
    delete_backup(root, second.name)
    assert list_backups(root) == []
    assert [p for p in (root / "files").rglob("*") if p.is_file()] == []
    with pytest.raises(BackupError):
        delete_backup(root, "../etc")


def test_schedule() -> None:
    monday_3 = datetime(2026, 11, 9, 3, 5, tzinfo=UTC)
    tuesday_3 = datetime(2026, 11, 10, 3, 5, tzinfo=UTC)
    assert due(None, "daily", 3, monday_3)
    assert not due(None, "daily", 4, monday_3)
    assert not due(None, "off", 3, monday_3)
    assert due(None, "weekly", 3, monday_3)
    assert not due(None, "weekly", 3, tuesday_3)
    assert not due(monday_3, "daily", 3, monday_3.replace(minute=50))


def test_backup_api(admin: TestClient, settings: Settings) -> None:
    listed = admin.get("/api/admin/backups").json()
    assert listed["backups"] == []
    assert listed["config"]["schedule"] == "off"
    config = {"schedule": "daily", "hour": 2, "with_files": False, "keep": 3}
    assert admin.put("/api/admin/backups/config", json=config).json() == config
    assert admin.get("/api/admin/backups").json()["config"] == config
    assert (
        admin.post("/api/admin/backups", json={"with_files": True}).status_code == 202
    )
    # Queued already: the worker writes one backup at a time.
    assert admin.post("/api/admin/backups", json={}).status_code == 409
    assert admin.delete("/api/admin/backups/nope").status_code == 404


def test_backup_api_is_for_admins(logged_in: TestClient) -> None:
    assert logged_in.get("/api/admin/backups").status_code == 403
    assert logged_in.post("/api/admin/backups", json={}).status_code == 403


def test_check_before_restoring(
    logged_in: TestClient, engine: Engine, blobs: BlobStore, tmp_path: Path
) -> None:
    fill(logged_in)
    root = tmp_path / "backups"
    full = create_backup(engine, blobs, root, with_files=True)
    (root / full.name).rename(root / "2000-01-01T00-00-00Z")
    only_db = create_backup(engine, blobs, root, with_files=False)

    # The storage survived: every file is already there.
    check = check_restore(blobs, root, only_db.name)
    assert (check.needed, check.in_storage, check.missing, check.extra) == (1, 1, 0, 0)

    # A new, empty storage: the full backup brings the file back ...
    empty = FilesystemStore(tmp_path / "new-storage")
    check = check_restore(empty, root, "2000-01-01T00-00-00Z")
    assert (check.from_backup, check.missing) == (1, 0)
    # ... the database-only one cannot: the paper would lack its PDF.
    check = check_restore(empty, root, only_db.name)
    assert (check.missing, check.affected, check.affected_count) == (
        1,
        ["Kept safe"],
        1,
    )

    # Files added after the backup are counted (and kept).
    extra = logged_in.post("/api/items", json={"metadata": {"title": "Later"}}).json()
    logged_in.post(
        f"/api/items/{extra['id']}/files",
        files={"upload": ("later.pdf", PDF + b"later", "application/pdf")},
    )
    assert check_restore(blobs, root, only_db.name).extra == 1
