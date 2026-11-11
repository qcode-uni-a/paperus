"""Backups: written from one snapshot, restored into an empty database."""

import gzip
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from sqlalchemy import Engine, make_url, text
from sqlalchemy.orm import Session

from paperus.app import create_app
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
from tests.conftest import FakeML, _recreate_database
from tests.people import Person, group

PDF = b"%PDF-1.7\n" + b"x" * 4000 + b"\n%%EOF\n"


@pytest.fixture
def restore_url(database_url: str) -> Iterator[str]:
    url = make_url(database_url)
    url = url.set(database=f"{url.database}_restore")
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
    assert listed["config"]["schedule"] == "daily"
    config = {"schedule": "daily", "hour": 2, "with_files": False, "keep": 3}
    assert admin.put("/api/admin/backups/config", json=config).json() == config
    assert admin.get("/api/admin/backups").json()["config"] == config
    assert (
        admin.post("/api/admin/backups", json={"with_files": True}).status_code == 202
    )
    # Queued already: the worker writes one backup at a time.
    assert admin.post("/api/admin/backups", json={}).status_code == 409
    assert admin.delete("/api/admin/backups/nope").status_code == 404


def test_deleting_a_backup(
    admin: TestClient, engine: Engine, blobs: BlobStore, settings: Settings
) -> None:
    backup = create_backup(engine, blobs, settings.backup_path, with_files=False)
    assert admin.delete(f"/api/admin/backups/{backup.name}").status_code == 204
    assert admin.get("/api/admin/backups").json()["backups"] == []


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


def test_odd_folders_and_backups(
    logged_in: TestClient,
    engine: Engine,
    blobs: BlobStore,
    tmp_path: Path,
) -> None:
    root = tmp_path / "backups"
    assert prune(root / "nowhere", keep=1) == []
    good = create_backup(engine, blobs, root, with_files=False)
    # Left by an interrupted backup: removed.
    (root / "2026-01-01T00-00-00Z.partial" / "tables").mkdir(parents=True)
    # Not a manifest paperus wrote: left out.
    (root / "2026-01-02T00-00-00Z").mkdir()
    (root / "2026-01-02T00-00-00Z" / "manifest.json").write_text("{}")
    assert [m.name for m in list_backups(root)] == [good.name]
    assert prune(root, keep=1) == []
    assert not (root / "2026-01-01T00-00-00Z.partial").exists()

    with pytest.raises(BackupError, match="no backup"):
        check_restore(blobs, root, "2026-01-03T00-00-00Z")
    manifest = root / good.name / "manifest.json"
    manifest.write_text(manifest.read_text().replace('"format": 1', '"format": 2'))
    settings = Settings(database_url=str(engine.url), storage_path=tmp_path / "x")
    with pytest.raises(BackupError, match="format 2"):
        restore_backup(settings, engine, blobs, root, good.name, replace=True)


def test_no_backup_of_a_database_without_schema(
    restore_url: str, blobs: BlobStore, tmp_path: Path
) -> None:
    empty = make_engine(restore_url)
    try:
        with empty.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num text)"))
        with pytest.raises(BackupError, match="no schema"):
            create_backup(empty, blobs, tmp_path / "backups", with_files=False)
    finally:
        empty.dispose()
    # Nothing half-written is left.
    assert list((tmp_path / "backups").iterdir()) == []


def test_check_leaves_out_what_is_in_the_trash(
    logged_in: TestClient, engine: Engine, blobs: BlobStore, tmp_path: Path
) -> None:
    fill(logged_in)
    for title in ("In the trash", "File in the trash"):
        item = logged_in.post("/api/items", json={"metadata": {"title": title}})
        logged_in.post(
            f"/api/items/{item.json()['id']}/files",
            files={"upload": ("p.pdf", PDF + title.encode(), "application/pdf")},
        )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE items SET deleted_at = now() WHERE title = 'In the trash'")
        )
        connection.execute(
            text(
                "UPDATE files SET deleted_at = now() FROM versions, items"
                " WHERE files.version_id = versions.id"
                " AND versions.item_id = items.id AND items.title = 'File in the trash'"
            )
        )
    root = tmp_path / "backups"
    backup = create_backup(engine, blobs, root, with_files=False)
    check = check_restore(FilesystemStore(tmp_path / "empty"), root, backup.name)
    assert (check.needed, check.missing, check.affected) == (1, 1, ["Kept safe"])


def test_restore_without_a_file_the_backup_lost(
    logged_in: TestClient,
    engine: Engine,
    blobs: BlobStore,
    tmp_path: Path,
    restore_url: str,
) -> None:
    fill(logged_in)
    root = tmp_path / "backups"
    backup = create_backup(engine, blobs, root, with_files=True)
    for path in (root / "files").rglob("*"):
        if path.is_file():
            path.unlink()
    store = FilesystemStore(tmp_path / "restored-files")
    settings = Settings(database_url=restore_url, storage_path=store.root)
    restored = make_engine(restore_url)
    try:
        restore_backup(settings, restored, store, root, backup.name, replace=False)
    finally:
        restored.dispose()
    assert list(store.iter_stored()) == []


MARK = {
    "kind": "note",
    "page_index": 0,
    "position": {"rects": [[10, 10, 20, 20]]},
    "color": "#ffd400",
    "comment": "Key result",
}


def what_one_sees(person: Person) -> dict[str, Any]:
    """Everything a person sees, for comparing before and after."""
    items = person.get("/api/items", {"limit": "200"}).json()
    files = [f["id"] for item in items for f in item["files"]]
    return {
        "items": sorted(item["title"] for item in items),
        "notes": sorted(note["title"] for note in person.get("/api/notes").json()),
        "tags": sorted(tag["name"] for tag in person.get("/api/tags").json()),
        "collections": sorted(c["name"] for c in person.get("/api/collections").json()),
        "groups": sorted(g["name"] for g in person.get("/api/groups").json()),
        "annotations": sorted(
            a["comment"] or ""
            for file in files
            for a in person.get(f"/api/files/{file}/annotations").json()["annotations"]
        ),
        "contents": sorted(
            hashlib.sha256(person.get(f"/api/files/{file}/content").content).hexdigest()
            for file in files
        ),
    }


def test_a_whole_library_comes_back(
    client: TestClient,
    db: Session,
    engine: Engine,
    blobs: BlobStore,
    tmp_path: Path,
    restore_url: str,
    job_app: App,
    fake_ml: FakeML,
) -> None:
    """A backup restored onto a fresh installation (#41): papers, files,
    notes, annotations, tags, collections, groups and sharing come back,
    and each person sees what they saw."""
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    lab = group(root, "Lab", ada)
    ada.put(f"/api/groups/{lab['id']}/members/{bob.id}", json={"role": "reader"})
    shared = ada.add("Shared paper", lab["library_id"])
    ada.add("Ada's own")
    file = ada.post(
        f"/api/items/{shared['id']}/files",
        files={"upload": ("paper.pdf", PDF, "application/pdf")},
    ).json()["id"]
    ada.note("# Seminar\n\nOn the shared paper", lab["library_id"], [shared["id"]])
    ada.note("# Private thoughts")
    ada.post(f"/api/items/{shared['id']}/tags", {"name": "optics"})
    shelf = ada.post(
        "/api/collections", {"name": "Shelf", "library_id": lab["library_id"]}
    ).json()
    ada.post(f"/api/collections/{shelf['id']}/items", {"item_ids": [shared["id"]]})
    ada.post(f"/api/files/{file}/annotations", MARK)
    bob.post(f"/api/files/{file}/annotations", MARK | {"comment": "Bob's own"})
    ada.put(f"/api/items/{shared['id']}/annotation-sharing", {"shared": True})
    seen = {name: what_one_sees(p) for name, p in (("ada", ada), ("bob", bob))}
    assert seen["bob"]["items"] == ["Shared paper"]
    assert seen["bob"]["annotations"] == ["Bob's own", "Key result"]
    assert seen["bob"]["notes"] == ["Seminar"]

    backups = tmp_path / "backups"
    manifest = create_backup(engine, blobs, backups, with_files=True)
    restored_files = tmp_path / "restored-files"
    settings = Settings(database_url=restore_url, storage_path=restored_files)
    restored_engine = make_engine(restore_url)
    try:
        restore_backup(
            settings,
            restored_engine,
            FilesystemStore(restored_files),
            backups,
            manifest.name,
            replace=False,
        )

        def rows(on: Engine) -> dict[str, int]:
            with on.connect() as connection:
                tables = connection.scalars(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).all()
                return {
                    table: connection.execute(
                        text(f'SELECT count(*) FROM "{table}"')
                    ).scalar_one()
                    for table in tables
                    # Job queue and log: the worker's, not the library's.
                    if not table.startswith(("procrastinate", "log_entries"))
                }

        assert rows(restored_engine) == rows(engine)
        # A fresh installation on the restored database and files: each
        # person logs in with their password and sees what they saw.
        app = create_app(settings, job_app=job_app, ml_client=fake_ml.client())
        with TestClient(app, base_url="https://testserver") as fresh:
            for name in ("ada", "bob"):
                login = fresh.post(
                    "/api/auth/login", json={"username": name, "password": "secret"}
                )
                again = Person.__new__(Person)
                again.client = fresh
                again.headers = {"Authorization": f"Bearer {login.json()['token']}"}
                assert what_one_sees(again) == seen[name], name
    finally:
        restored_engine.dispose()
