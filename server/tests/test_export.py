"""Exports: what a person can see, as library.sqlite and files in zips."""

import hashlib
import io
import json
import re
import sqlite3
import uuid
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from paperus import export, library
from paperus.access import Access
from paperus.cli import main
from paperus.config import Settings
from paperus.db import make_sessionmaker
from paperus.importing import Export as ImportedExport
from paperus.importing import bibtex, ris, zotero
from paperus.models import Blob, Export, ExportStatus, File, Item, User
from paperus.storage import BlobStore
from tests.export_library import (
    Rich,
    build,
    database,
    exported,
    rows,
    run_exports,
    run_imports,
    upload,
    upload_export,
)
from tests.people import Person

Runner = Callable[..., list[Path]]


@pytest.fixture
def rich(client: TestClient, db: Session) -> Rich:
    return build(client, db)


@pytest.fixture
def run(
    job_app: App, engine: Engine, blobs: BlobStore, settings: Settings, tmp_path: Path
) -> Runner:
    """Export as a person (options as the API takes them); its zips."""
    count = iter(range(1000))

    def run(person: Person, **options: object) -> list[Path]:
        folder = tmp_path / f"export-{next(count)}"
        return exported(person, job_app, engine, blobs, settings, folder, **options)

    return run


def column(connection: sqlite3.Connection, table: str, name: str) -> list[Any]:
    return sorted((row[name] for row in rows(connection, table)), key=lambda v: str(v))


def test_the_export_holds_what_the_person_sees(
    rich: Rich,
    run: Runner,
    tmp_path: Path,
    blobs: BlobStore,
) -> None:
    parts = run(rich.ada)
    assert len(parts) == 1
    assert re.fullmatch(r"paperus-export-\d{4}-\d\d-\d\d-\d{4}\.zip", parts[0].name)
    data = database(parts[0], tmp_path)
    ids = rich.ids

    # Papers: hers and her groups', archived too; not bob's, not the trash.
    assert column(data, "items", "title") == [
        "Old notes on rain",
        "Qubits in the lab",
        "Radar gaps over the Alps",
        "Uni handbook",
    ]
    radar = next(r for r in rows(data, "items") if r["id"] == str(ids["radar"]))
    assert json.loads(radar["overrides"]) == {"title-short": "Radar", "note": None}
    assert radar["library_id"] == str(ids["mine"])
    assert radar["references_source"] == "crossref"
    assert radar["created_at"].endswith("Z") and radar["file_wanted"] == 1
    old = next(r for r in rows(data, "items") if r["id"] == str(ids["old"]))
    assert old["archived_at"] is not None
    versions = [r for r in rows(data, "versions") if r["item_id"] == str(ids["radar"])]
    assert sorted((v["kind"], v["label"]) for v in versions) == [
        ("preprint", "v2"),
        ("published", None),
    ]
    published = next(v for v in versions if v["kind"] == "published")
    assert json.loads(published["csl"])["DOI"] == "10.1234/radar"
    assert published["metadata_source"] == "manual" and published["pinned"] == 0
    assert sorted((r["scheme"], r["value"]) for r in rows(data, "identifiers")) == [
        ("arxiv", "2401.00001"),
        ("doi", "10.1234/radar"),
        ("doi", "10.5555/qubits"),
    ]

    # Owners and people: names only.
    owners = {r["name"]: r for r in rows(data, "owners")}
    assert set(owners) == {"Me", "Uni", "Uni/QCode Lab"}
    assert owners["Me"]["kind"] == "me" and owners["Me"]["role"] is None
    assert owners["Uni"]["role"] == "reader"
    assert owners["Uni/QCode Lab"]["role"] == "member"
    assert owners["Uni/QCode Lab"]["id"] == str(ids["lab"])
    assert sorted(column(data, "users", "username")) == ["ada", "bob"]
    users = data.execute("SELECT * FROM users").fetchone()
    assert set(users.keys()) == {"id", "username"}

    # Tags: hers, the group's; not bob's private ones.
    tags = {r["name"]: r for r in rows(data, "tags")}
    assert set(tags) == {"to read", "physics", "suggested", "mine", "lab topic"}
    assert tags["to read"]["color"] == "red"
    assert tags["to read"]["description"] == "Next week"
    sources = {
        (tags_by_id(data)[r["tag_id"]], r["source"]) for r in rows(data, "item_tags")
    }
    assert sources == {
        ("to read", "manual"),
        ("physics", "automatic"),
        ("suggested", "ai"),
        ("mine", "manual"),
        ("lab topic", "manual"),
    }

    # Collections: hers (nested, smart) and the group's; not bob's.
    collections = {r["name"]: r for r in rows(data, "collections")}
    assert set(collections) == {"Thesis", "Chapter 1", "Physics", "Lab reading"}
    assert collections["Chapter 1"]["parent_id"] == str(ids["thesis"])
    rules = json.loads(collections["Physics"]["rules"])
    assert rules["tags_any"] == [str(ids["physics"])]
    held = {(r["collection_id"], r["item_id"]) for r in rows(data, "collection_items")}
    assert held == {
        (str(ids["chapter"]), str(ids["radar"])),
        (str(ids["chapter"]), str(ids["lab_paper"])),
        (str(ids["reading"]), str(ids["lab_paper"])),
    }

    # Notes: hers and the group's, with their links; not bob's.
    assert sorted(column(data, "notes", "title")) == [
        "Ideas for chapter 2",
        "Lab meeting: qubits",
        "Reading radar",
    ]
    links = {(r["note_id"], r["item_id"], r["page"]) for r in rows(data, "note_items")}
    assert links == {
        (str(ids["note"]), str(ids["radar"]), 2),
        (str(ids["lab_note"]), str(ids["lab_paper"]), None),
    }
    assert [
        (r["collection_id"], r["note_id"]) for r in rows(data, "collection_notes")
    ] == [(str(ids["chapter"]), str(ids["note"]))]

    # Her own view.
    assert [r["item_id"] for r in rows(data, "favourites")] == [str(ids["radar"])]
    assert [r["collection_id"] for r in rows(data, "pinned_collections")] == [
        str(ids["thesis"])
    ]
    references = rows(data, "item_references")
    assert [(r["position"], r["doi"]) for r in references] == [
        (1, None),
        (2, "10.1/engine"),
    ]

    # Files: once each, readable names, the right bytes.
    files = {r["filename"]: r for r in rows(data, "files")}
    assert set(files) == {"radar.pdf", "data.csv", "lab.pdf"}
    assert (
        files["radar.pdf"]["path"]
        == "files/van Gogh 2025 - Radar gaps over the Alps.pdf"
    )
    assert files["data.csv"]["path"] == (
        "files/van Gogh 2025 - Radar gaps over the Alps (supplementary).csv"
    )
    assert files["lab.pdf"]["path"] == "files/Lovelace 1843 - Qubits in the lab.pdf"
    name = parts[0].name.removesuffix(".zip")
    with zipfile.ZipFile(parts[0]) as archive:
        entries = archive.infolist()
        assert [e.filename for e in entries[:3]] == [
            f"{name}/library.sqlite",
            f"{name}/part.json",
            f"{name}/README.txt",
        ]
        assert entries[0].compress_type == zipfile.ZIP_DEFLATED
        for row in files.values():
            info = archive.getinfo(f"{name}/{row['path']}")
            content = archive.read(info)
            assert hashlib.sha256(content).hexdigest() == row["sha256"]
            assert len(content) == row["size"] and row["included"] == 1
            assert row["part"] == 1
            stored = row["media_type"] == "application/pdf"
            assert info.compress_type == (
                zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            )
        marker = json.loads(archive.read(f"{name}/part.json"))
        readme = archive.read(f"{name}/README.txt").decode()
    assert marker["part"] == 1 and marker["parts"] == 1
    assert "library.sqlite" in readme and "unzip paperus-export-" in readme
    assert "sqlite3 library.sqlite .dump" in readme

    meta = rows(data, "paperus")[0]
    assert meta["format"] == "paperus-export" and meta["format_version"] == 1
    assert meta["exported_by"] == "ada" and meta["export_id"] == marker["export"]
    assert meta["parts"] == 1 and meta["name"] == name
    assert json.loads(meta["options"])["include"]["files"] is True
    data.close()


def tags_by_id(data: sqlite3.Connection) -> dict[str, str]:
    return {r["id"]: r["name"] for r in rows(data, "tags")}


def test_the_trash_only_when_asked(
    rich: Rich,
    run: Runner,
    tmp_path: Path,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Rows go to SQLite a few at a time; a pinned version names the files.
    monkeypatch.setattr(export, "BATCH", 2)
    radar = db.get_one(Item, rich.ids["radar"])
    preprint = next(v for v in radar.versions if v.kind == "preprint")
    library.pin_version(db, radar, preprint)
    db.commit()
    data = database(run(rich.ada, trash=True)[0], tmp_path)
    assert "files/van Gogh 2024 - Radar gaps over the Alps.pdf" in column(
        data, "files", "path"
    )
    assert "Trashed draft" in column(data, "items", "title")
    trashed = next(r for r in rows(data, "items") if r["title"] == "Trashed draft")
    assert trashed["deleted_at"] is not None
    assert "draft.txt" in column(data, "files", "filename")
    data.close()


@pytest.mark.parametrize(
    "left_out",
    ["notes", "tags", "collections", "references", "authors", "files", "archived"],
)
def test_each_part_can_be_left_out(
    rich: Rich,
    run: Runner,
    tmp_path: Path,
    left_out: str,
) -> None:
    parts = run(rich.ada, include={left_out: False})
    data = database(parts[0], tmp_path)
    counts = {table: len(rows(data, table)) for table in export.TABLES}
    empty = {
        "notes": {"notes", "note_items", "collection_notes"},
        "tags": {"tags", "item_tags"},
        "collections": {
            "collections",
            "collection_items",
            "collection_notes",
            "pinned_collections",
        },
        "references": {"item_references"},
        "authors": {"authors", "authorships"},
        "files": set(),
        "archived": set(),
    }[left_out]
    for table, count in counts.items():
        assert (count == 0) == (table in empty), (table, count)
    included = column(data, "files", "included")
    with zipfile.ZipFile(parts[0]) as archive:
        names = archive.namelist()
    if left_out == "files":
        assert included == [0, 0, 0] and column(data, "files", "path") == [None] * 3
        assert not [n for n in names if "/files/" in n]
    else:
        assert included == [1, 1, 1]
    titles = column(data, "items", "title")
    assert ("Old notes on rain" in titles) == (left_out != "archived")
    assert json.loads(rows(data, "paperus")[0]["options"])["include"][left_out] is False
    data.close()


def test_only_some_owners(rich: Rich, run: Runner, tmp_path: Path) -> None:
    data = database(run(rich.ada, owners=[str(rich.ids["lab"])])[0], tmp_path)
    assert column(data, "items", "title") == ["Qubits in the lab"]
    assert column(data, "notes", "title") == ["Lab meeting: qubits"]
    assert column(data, "collections", "name") == ["Lab reading"]
    # Her private tag on the group's paper comes along, with its owner.
    assert column(data, "tags", "name") == ["lab topic", "mine"]
    assert column(data, "owners", "name") == ["Me", "Uni/QCode Lab"]
    data.close()


def test_one_collection(rich: Rich, run: Runner, tmp_path: Path) -> None:
    data = database(run(rich.ada, collection_id=str(rich.ids["thesis"]))[0], tmp_path)
    assert column(data, "collections", "name") == ["Chapter 1", "Thesis"]
    assert column(data, "items", "title") == [
        "Qubits in the lab",
        "Radar gaps over the Alps",
    ]
    # Notes filed there or about its papers.
    assert column(data, "notes", "title") == ["Lab meeting: qubits", "Reading radar"]
    assert column(data, "tags", "name") == [
        "lab topic",
        "mine",
        "physics",
        "suggested",
        "to read",
    ]
    assert column(data, "owners", "name") == ["Me", "Uni/QCode Lab"]
    assert (
        json.loads(rows(data, "paperus")[0]["options"])["collection_name"] == "Thesis"
    )
    data.close()

    # A smart collection: the papers matching it; a sub-collection at the top.
    data = database(run(rich.ada, collection_id=str(rich.ids["smart"]))[0], tmp_path)
    assert column(data, "items", "title") == ["Radar gaps over the Alps"]
    data.close()
    data = database(run(rich.ada, collection_id=str(rich.ids["chapter"]))[0], tmp_path)
    assert column(data, "collections", "parent_id") == [None]
    data.close()


def test_large_exports_come_in_parts(
    client: TestClient,
    db: Session,
    rich: Rich,
    blobs: BlobStore,
    tmp_path: Path,
) -> None:
    access = Access.of(db, db.get_one(User, uuid.UUID(rich.ada.id)))
    # A large file: larger than a part may be.
    big = bytes(range(256)) * 40
    item = rich.ada.add("Big data")
    upload(
        rich.ada,
        uuid.UUID(item["id"]),
        "big.bin",
        big,
        "application/octet-stream",
        "main",
    )
    folder = tmp_path / "parts"
    folder.mkdir()
    written = export.write_export(
        db,
        blobs,
        access,
        export.Options(),
        folder,
        export_id=uuid.uuid4(),
        server_url="https://paperus.example.org",
        part_limit=9000,
    )
    db.rollback()
    names = [part.name for part in written.parts]
    count = len(names)
    assert count == 3
    stem = names[0].removesuffix("-part1-of-3.zip")
    assert names == [f"{stem}-part{n}-of-{count}.zip" for n in range(1, count + 1)]
    data = database(folder / names[0], tmp_path)
    where = {}
    for n, name in enumerate(names, 1):
        with zipfile.ZipFile(folder / name) as archive:
            members = archive.namelist()
            first = json.loads(archive.read(f"{stem}/part.json"))
            assert first["part"] == n and first["parts"] == count
            if n > 1:
                assert members[0] == f"{stem}/part.json"
                assert f"{stem}/library.sqlite" not in members
            for member in members:
                if "/files/" in member:
                    where[member.split("/", 1)[1]] = n
    for row in rows(data, "files"):
        assert where[row["path"]] == row["part"]
    big_row = next(r for r in rows(data, "files") if r["filename"] == "big.bin")
    alone = [path for path, part in where.items() if part == big_row["part"]]
    assert alone == [big_row["path"]] and big_row["path"].endswith(".bin")
    with zipfile.ZipFile(folder / names[0]) as archive:
        readme = archive.read(f"{stem}/README.txt").decode()
    assert f"in {count} zips" in readme and "a zip of its own" in readme
    assert "https://paperus.example.org" in readme
    assert rows(data, "paperus")[0]["parts"] == count
    data.close()


def test_only_the_database_without_the_files(
    rich: Rich,
    run: Runner,
    tmp_path: Path,
) -> None:
    """library.sqlite is the first entry: taken alone, the files untouched."""
    part1 = run(rich.ada)[0]

    class Counting(io.FileIO):
        read_bytes = 0

        def read(self, size: int | None = -1, /) -> bytes:
            data = super().read(size)
            Counting.read_bytes += len(data)
            return data

    with Counting(part1, "rb") as raw, zipfile.ZipFile(raw) as archive:
        first = archive.infolist()[0]
        assert first.filename.endswith("/library.sqlite")
        Counting.read_bytes = 0
        archive.extract(first, tmp_path / "only")
        # The database (compressed) and its header, nothing else.
        assert Counting.read_bytes < first.compress_size + 200
    extracted = next((tmp_path / "only").rglob("library.sqlite"))
    assert extracted.read_bytes()[:15] == b"SQLite format 3"


def test_download_answers_range_requests(
    rich: Rich,
    run: Runner,
    client: TestClient,
) -> None:
    run(rich.ada)
    record = rich.ada.get("/api/exports").json()[0]
    url = f"/api/exports/{record['id']}/parts/1"
    whole = rich.ada.get(url)
    assert whole.headers["accept-ranges"] == "bytes"
    assert "attachment" in whole.headers["content-disposition"]
    assert record["parts"][0]["name"] in whole.headers["content-disposition"]
    end = client.get(url, headers={**rich.ada.headers, "Range": "bytes=-22"})
    assert end.status_code == 206
    assert end.content == whole.content[-22:]
    assert end.content.startswith(b"PK\x05\x06")  # the zip's directory end
    # Others never see it; parts that are not there are not there.
    assert rich.bob.get(url).status_code == 404
    assert rich.bob.get(f"/api/exports/{record['id']}").status_code == 404
    assert rich.ada.get(f"/api/exports/{record['id']}/parts/2").status_code == 404


def test_each_part_as_soon_as_it_is_written(
    rich: Rich,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zip can be downloaded once written, and the person is told."""
    export_id = rich.ada.post("/api/exports", json={}).json()["id"]
    url = f"/api/exports/{export_id}/parts"
    downloads: list[tuple[str, int, int, int]] = []
    write = export.write_export

    def watched(*args: Any, finished: Callable[..., None], **kwargs: Any) -> Any:  # noqa: ANN401
        def told(parts: list[export.Part], count: int) -> None:
            finished(parts, count)
            record = rich.ada.get(f"/api/exports/{export_id}").json()
            n = len(parts)
            # This one can be downloaded; the next one not yet.
            downloads.append(
                (
                    record["status"],
                    len(record["parts"]),
                    rich.ada.get(f"{url}/{n}").status_code,
                    rich.ada.get(f"{url}/{n + 1}").status_code,
                )
            )

        return write(*args, finished=told, **kwargs)

    monkeypatch.setattr(export, "write_export", watched)
    export.run(
        make_sessionmaker(engine),
        blobs,
        settings,
        uuid.UUID(export_id),
        part_limit=1500,
    )
    count = len(downloads)
    assert count > 2
    assert downloads == [("running", n, 200, 404) for n in range(1, count + 1)]
    # One notification per part; the last one once the export is done.
    assert exports_told(rich.ada) == [
        ("export", {"export_id": export_id, "part": n, "parts": count})
        for n in range(count, 0, -1)
    ]
    assert exports_told(rich.bob) == []


def test_a_failure_takes_the_parts_written(
    rich: Rich,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_id = rich.ada.post("/api/exports", json={}).json()["id"]
    write = export.write_export

    def failing(*args: Any, finished: Callable[..., None], **kwargs: Any) -> Any:  # noqa: ANN401
        def told(parts: list[export.Part], count: int) -> None:
            finished(parts, count)
            raise OSError("no space left")

        return write(*args, finished=told, **kwargs)

    monkeypatch.setattr(export, "write_export", failing)
    export.run(
        make_sessionmaker(engine),
        blobs,
        settings,
        uuid.UUID(export_id),
        part_limit=1500,
    )
    record = rich.ada.get(f"/api/exports/{export_id}").json()
    assert record["status"] == "failed" and record["parts"] == []
    assert record["error"] == "The export stopped: no space left"
    assert rich.ada.get(f"/api/exports/{export_id}/parts/1").status_code == 404
    assert not export.folder_of(settings, uuid.UUID(export_id)).exists()
    [failed, first] = exports_told(rich.ada)
    assert failed == ("export_failed", {"export_id": export_id})
    assert first[1]["part"] == 1


def exports_told(person: Person) -> list[tuple[str, dict[str, Any]]]:
    """The person's notifications about exports, newest first."""
    notices = person.get("/api/me/notifications").json()["notifications"]
    return [(n["kind"], n["data"]) for n in notices if n["kind"].startswith("export")]


def test_estimate(rich: Rich) -> None:
    estimate = rich.ada.post("/api/exports/estimate", json={}).json()
    files = [rich.pdfs["radar"], b"x,y\n1,2\n", rich.pdfs["lab"]]
    assert estimate["items"] == 4 and estimate["notes"] == 3
    assert estimate["collections"] == 4 and estimate["files"] == 3
    assert estimate["files_bytes"] == sum(len(f) for f in files)
    assert estimate["parts"] == 1 and estimate["size"] > estimate["files_bytes"]
    without = rich.ada.post(
        "/api/exports/estimate", json={"include": {"files": False}, "trash": True}
    ).json()
    assert without["files"] == 0 and without["items"] == 5
    trash = rich.ada.post("/api/exports/estimate", json={"trash": True}).json()
    assert trash["files"] == 4


def test_what_may_be_asked_for(rich: Rich) -> None:
    assert rich.ada.post("/api/exports", json={"owners": []}).status_code == 422
    secret = {"owners": [str(rich.ids["mine"]), str(uuid.uuid4())]}
    assert rich.ada.post("/api/exports", json=secret).status_code == 404
    hidden = {"collection_id": str(rich.ids["hidden"])}
    assert rich.ada.post("/api/exports", json=hidden).status_code == 404
    assert rich.ada.post("/api/exports/estimate", json=hidden).status_code == 404
    assert rich.ada.get(f"/api/exports/{uuid.uuid4()}").status_code == 404


def test_listing_and_deleting(
    rich: Rich,
    run: Runner,
    db: Session,
    settings: Settings,
) -> None:
    run(rich.ada, collection_id=str(rich.ids["thesis"]))
    listed = rich.ada.get("/api/exports").json()
    assert [e["collection_name"] for e in listed] == ["Thesis"]
    record = listed[0]
    assert record["status"] == "done" and record["done"] == record["total"] == 4
    assert record["size"] == sum(p["size"] for p in record["parts"])
    expires = datetime.fromisoformat(record["expires_at"])
    assert timedelta(hours=23) < expires - datetime.now(UTC) <= timedelta(hours=24)
    assert rich.bob.get("/api/exports").json() == []
    folder = export.folder_of(settings, uuid.UUID(record["id"]))
    assert folder.is_dir()
    assert rich.bob.delete(f"/api/exports/{record['id']}").status_code == 404
    db.get_one(Export, uuid.UUID(record["id"])).status = ExportStatus.RUNNING
    db.commit()
    assert rich.ada.delete(f"/api/exports/{record['id']}").status_code == 409
    db.get_one(Export, uuid.UUID(record["id"])).status = ExportStatus.DONE
    db.commit()
    assert rich.ada.delete(f"/api/exports/{record['id']}").status_code == 204
    assert not folder.exists() and rich.ada.get("/api/exports").json() == []


def test_expired_exports_are_removed(
    rich: Rich,
    run: Runner,
    client: TestClient,
    db: Session,
    settings: Settings,
) -> None:
    run(rich.ada)
    run(rich.ada, include={"files": False})
    first, second = rich.ada.get("/api/exports").json()[::-1]
    stray = settings.exports_folder / "left-over.partial"
    stray.mkdir()
    (settings.exports_folder / "stray.zip").write_bytes(b"x")
    record = db.get_one(Export, uuid.UUID(first["id"]))
    record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    gone = Export(
        user_id=uuid.UUID(rich.ada.id),
        status=ExportStatus.FAILED,
        options={},
        parts=[],
        created_at=datetime.now(UTC) - timedelta(days=9),
    )
    db.add(gone)
    db.commit()
    assert export.remove_expired(db, settings) == 1
    listed = {e["id"]: e for e in rich.ada.get("/api/exports").json()}
    assert listed[first["id"]]["status"] == "expired"
    assert listed[second["id"]]["status"] == "done"
    assert str(gone.id) not in listed
    url = f"/api/exports/{first['id']}/parts/1"
    assert rich.ada.get(url).status_code == 404
    # Followed in a browser (from a notification): to the exports instead.
    browsing = {**rich.ada.headers, "Accept": "text/html,*/*"}
    for link in (url, f"/api/exports/{uuid.uuid4()}/parts/1"):
        response = client.get(link, headers=browsing, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].endswith("/settings?open=export")
    assert not export.folder_of(settings, uuid.UUID(first["id"])).exists()
    assert export.folder_of(settings, uuid.UUID(second["id"])).is_dir()
    assert not stray.exists()
    assert not (settings.exports_folder / "stray.zip").exists()


def test_failures_are_reported(
    rich: Rich,
    db: Session,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    job_app: App,
) -> None:
    response = rich.ada.post("/api/exports", json={})
    export_id = uuid.UUID(response.json()["id"])
    db.get_one(User, uuid.UUID(rich.ada.id)).deactivated_at = datetime.now(UTC)
    db.commit()
    assert run_exports(job_app, engine, blobs, settings) == 1
    record = db.get_one(Export, export_id)
    db.refresh(record)
    assert record.status == ExportStatus.FAILED
    assert record.error == "The person who asked for it cannot log in."
    assert not list(settings.exports_folder.iterdir())
    db.get_one(User, uuid.UUID(rich.ada.id)).deactivated_at = None
    db.commit()
    assert exports_told(rich.ada) == [("export_failed", {"export_id": str(export_id)})]
    # Done (or gone) exports are not written again.
    export.run(make_sessionmaker(engine), blobs, settings, export_id)
    export.run(make_sessionmaker(engine), blobs, settings, uuid.uuid4())
    db.refresh(record)
    assert record.status == ExportStatus.FAILED


def test_a_file_missing_from_the_store(
    rich: Rich,
    run: Runner,
    db: Session,
    blobs: BlobStore,
    tmp_path: Path,
) -> None:
    sha = db.scalars(select(File.blob_sha256).where(File.filename == "data.csv")).one()
    blobs.delete(sha)
    parts = run(rich.ada)
    data = database(parts[0], tmp_path)
    csv = next(r for r in rows(data, "files") if r["filename"] == "data.csv")
    assert csv["included"] == 0 and csv["path"] is None and csv["part"] is None
    with zipfile.ZipFile(parts[0]) as archive:
        readme = archive.read(
            next(n for n in archive.namelist() if n.endswith("README.txt"))
        )
    assert b"1 file was missing" in readme
    assert db.get(Blob, sha) is not None
    data.close()
    (zotero_part,) = run(rich.ada, format="zotero")
    with zipfile.ZipFile(zotero_part) as archive:
        readme = archive.read(archive.namelist()[2])
    assert b"Files missing on the server: 1." in readme


def test_file_names() -> None:
    assert export.safe_name(' a/b:c*?"<>| . ') == "a b c"
    assert export.safe_name("CON") == "_CON"
    assert export.safe_name("...") == "_"
    assert len(export.safe_name("x" * 500)) == export.STEM_LENGTH
    assert export.extension("application/pdf", "x") == ".pdf"
    assert export.extension("application/octet-stream", "Data.TXT") == ".txt"
    assert export.extension("application/x-unknown-thing", "noext") == ""
    names = export.Names()
    assert names.add("Ada 1843 - Notes", ".pdf") == "Ada 1843 - Notes.pdf"
    assert names.add("ada 1843 - notes", ".pdf") == "ada 1843 - notes (2).pdf"
    assert export.file_stem({}) == "Unknown n.d. - Untitled"
    long = export.file_stem({"title": "word " * 40, "author": [{"literal": "WHO"}]})
    assert long.startswith("WHO n.d. - word") and len(long) < 80
    assert export.deflated("text/csv") and not export.deflated("application/pdf")


def test_the_parts_plan() -> None:
    files = [
        export.PlannedFile(bytes([n]), "x", size, compressed=False)
        for n, size in enumerate([400, 400, 5000, 100])
    ]
    assert export.plan(100, files, limit=1500) == [1, 1, 2, 3]
    assert export.plan(100, [], limit=1500) == []


def test_command_line(
    rich: Rich,
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    settings: Settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PAPERUS_DATABASE_URL", database_url)
    monkeypatch.setenv("PAPERUS_STORAGE_PATH", str(settings.storage_path))

    def cli(*argv: str) -> tuple[int, str]:
        try:
            main(list(argv))
        except SystemExit as exit:
            out, err = capsys.readouterr()
            return int(exit.code or 0), out + err
        raise AssertionError("no exit")

    out = tmp_path / "ada.zip"
    code, said = cli(
        "export", str(out), "--user", "ada", "--owner", "QCode Lab", "--no-files"
    )
    assert code == 0, said
    assert f"Wrote {out}" in said
    data = database(out, tmp_path)
    assert column(data, "items", "title") == ["Qubits in the lab"]
    assert column(data, "files", "included") == [0]
    data.close()
    code, said = cli(
        "export",
        str(out),
        "--user",
        "ada",
        "--no-notes",
        "--no-tags",
        "--no-collections",
        "--no-references",
        "--no-archive",
        "--trash",
        "--collection",
        str(rich.ids["thesis"]),
    )
    assert code == 0, said
    code, said = cli("export", str(out), "--user", "ada", "--format", "mendeley")
    assert code == 0, said
    with zipfile.ZipFile(out) as archive:
        assert archive.namelist()[0].endswith("-mendeley/paperus.ris")
    assert cli("export", str(out), "--user", "nobody") == (1, "No user 'nobody'.\n")
    assert cli("export", str(out), "--user", "ada", "--owner", "Chair")[0] == 1
    code, said = cli(
        "export", str(out), "--user", "ada", "--collection", str(uuid.uuid4())
    )
    assert (code, said) == (1, "No such collection.\n")


@pytest.mark.parametrize(
    ("program", "filename", "reader"),
    [
        ("zotero", "paperus.rdf", zotero.read),
        ("jabref", "paperus.bib", bibtex.read),
        ("mendeley", "paperus.ris", ris.read),
    ],
)
def test_for_other_programs(
    rich: Rich,
    run: Runner,
    program: str,
    filename: str,
    reader: Callable[[str], ImportedExport],
) -> None:
    (part,) = run(rich.ada, format=program)
    assert part.name.endswith(f"-{program}.zip")
    top = part.name.removesuffix(".zip")
    with zipfile.ZipFile(part) as archive:
        names = archive.namelist()
        assert names[:3] == [
            f"{top}/{filename}",
            f"{top}/part.json",
            f"{top}/README.txt",
        ]
        marker = json.loads(archive.read(f"{top}/part.json"))
        readme = archive.read(f"{top}/README.txt").decode()
        written = reader(archive.read(f"{top}/{filename}").decode())
    assert marker["contents"] == program
    assert readme.startswith(f"paperus export for {export.PROGRAMS[program]} of ada")
    papers = {p.csl.get("title"): p for p in written.papers}
    assert set(papers) == {
        "Radar gaps over the Alps",
        "Old notes on rain",
        "Qubits in the lab",
        "Uni handbook",
    }
    radar = papers["Radar gaps over the Alps"]
    # The shown version's details and identifiers.
    assert radar.csl.get("container-title") == "Journal of Weather"
    assert ("doi", "10.1234/radar") in [(s.value, v) for s, v in radar.identifiers]
    words = {*radar.tags, *radar.keywords}
    assert words == {"to read", "suggested", "physics"}
    if program == "zotero":
        assert set(radar.keywords) == {"physics"}
    assert any("Good figures" in note for note in radar.notes)
    # Files: where the file says, in the zip.
    paths = [f.path for p in written.papers for f in p.files]
    assert len(paths) == 3
    for path in paths:
        assert f"{top}/{path.replace(chr(92), '/')}" in names, path
    if program == "mendeley":
        assert "RIS has no collections" in readme
        assert all(not p.collections for p in written.papers)
    else:
        assert ("ada", "Thesis", "Chapter 1") in radar.collections
        assert ("ada", "Physics") in radar.collections  # smart: its papers now
        lab = papers["Qubits in the lab"]
        assert ("QCode Lab", "Lab reading") in lab.collections
    if program == "zotero":
        assert [n.text for n in written.notes if "chapter 2" in n.text]
    else:
        assert "not in the file" in readme


def test_other_programs_follow_the_choices(
    rich: Rich,
    run: Runner,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    (part,) = run(
        rich.ada,
        format="zotero",
        owners=[str(rich.ids["mine"])],
        include={"files": False, "notes": False, "tags": False, "archived": False},
    )
    top = part.name.removesuffix(".zip")
    with zipfile.ZipFile(part) as archive:
        assert not [n for n in archive.namelist() if "/files/" in n]
        written = zotero.read(archive.read(f"{top}/paperus.rdf").decode())
    assert [p.csl.get("title") for p in written.papers] == ["Radar gaps over the Alps"]
    radar = written.papers[0]
    assert not radar.files and not radar.notes and not radar.tags
    # One owner: no owner's name above the collections.
    assert ("Thesis", "Chapter 1") in radar.collections
    # paperus imports it as a Zotero export (not as its own).
    response = upload_export(rich.ada, [part])
    assert response.status_code == 201 and response.json()["status"] == "waiting"
    run_imports(db, blobs, job_app)
    record = rich.ada.get(f"/api/imports/{response.json()['id']}").json()
    assert record["status"] == "done" and record["format"] == "zotero-rdf"
    assert record["report"]["found"] == 1


def test_other_programs_in_parts(
    rich: Rich, db: Session, blobs: BlobStore, tmp_path: Path
) -> None:
    access = Access.of(db, db.get_one(User, uuid.UUID(rich.ada.id)))
    written = export.write_export(
        db,
        blobs,
        access,
        export.Options(format="jabref"),
        tmp_path,
        export_id=uuid.uuid4(),
        part_limit=1500,
    )
    db.rollback()
    count = len(written.parts)
    assert count > 1 and written.parts[0].files == 0
    top = written.parts[0].name.removesuffix(f"-part1-of-{count}.zip")
    with zipfile.ZipFile(tmp_path / written.parts[0].name) as archive:
        readme = archive.read(f"{top}/README.txt").decode()
    assert f"in {count} zips" in readme
    assert f"{top}-part{count}-of-{count}.zip: 1 file\r\n" in readme
