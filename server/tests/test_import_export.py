"""Importing a paperus export back: owners chosen first, nothing lost,
nothing added twice."""

import hashlib
import json
import sqlite3
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from paperus import export, jobs
from paperus.access import Access
from paperus.cli import _other_parts as other_parts
from paperus.cli import main
from paperus.config import Settings
from paperus.db import make_sessionmaker
from paperus.export import TABLES
from paperus.importing import paperus_export
from paperus.importing.run import run_import
from paperus.models import (
    Blob,
    Collection,
    CollectionItem,
    CollectionNote,
    Export,
    Favourite,
    File,
    Identifier,
    Import,
    ImportPart,
    Item,
    ItemReference,
    ItemTag,
    Library,
    Note,
    NoteItem,
    PinnedCollection,
    Tag,
    User,
    Version,
)
from paperus.organize import Rules
from paperus.storage import BlobStore
from tests.conftest import FakeML
from tests.export_library import (
    Rich,
    build,
    database,
    empty_database,
    exported,
    rows,
    run_imports,
    upload,
    upload_export,
    zip_bytes,
)
from tests.people import Person


@pytest.fixture
def job_app(monkeypatch: pytest.MonkeyPatch) -> App:
    """Jobs in memory, which a worker can run by their names (as in
    test_worker.py)."""
    app = App(connector=InMemoryConnector())
    for task in set(jobs.tasks.tasks.values()):
        name = f"paperus:{task.name.rsplit(':', 1)[-1]}"
        monkeypatch.setattr(task, "name", name)
        monkeypatch.setattr(task, "blueprint", app)
        app.tasks[name] = task
    return app


USER_COLUMNS = {
    "added_by",
    "created_by",
    "changed_by",
    "deleted_by",
    "uploaded_by",
    "user_id",
}
# Moved by the import itself: when it happened.
NOW_COLUMNS = {"changed_at"}


def normalized(
    connection: sqlite3.Connection, owners: dict[str, str]
) -> dict[str, list[dict[str, Any]]]:
    """Every table's rows, people and owners as placeholders, sorted."""
    found: dict[str, list[dict[str, Any]]] = {}
    for table in TABLES:
        if table in ("paperus", "users", "owners"):
            continue
        result = []
        for row in rows(connection, table):
            for column in list(row):
                if column in USER_COLUMNS and row[column] is not None:
                    row[column] = "someone"
                elif column in NOW_COLUMNS:
                    row[column] = "now"
                elif column == "library_id":
                    row[column] = owners.get(row[column], row[column])
                elif column == "rules" and row[column]:
                    rules = Rules.model_validate_json(row[column])
                    rules = rules.model_dump(mode="json")
                    rules["owners"] = [owners.get(o, o) for o in rules["owners"]]
                    row[column] = json.dumps(rules, sort_keys=True)
            result.append(row)
        found[table] = sorted(result, key=lambda r: json.dumps(r, sort_keys=True))
    return found


def test_round_trip_into_an_empty_server(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
) -> None:
    rich = build(client, db)
    parts = exported(
        rich.ada, job_app, engine, blobs, settings, tmp_path / "first", trash=True
    )
    before = database(parts[0], tmp_path / "first")
    db.rollback()
    empty_database(engine)
    db.expire_all()

    carol = Person(client, db, "carol")
    response = upload_export(carol, parts)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["status"] == "needs_choices"
    choices = record["choices"]
    assert [o["name"] for o in choices["owners"]] == ["Me", "Uni", "Uni/QCode Lab"]
    assert choices["missing"] == [] and choices["refused"] == []
    started = start(carol, record)
    assert started.status_code == 200, started.text
    queued = run_imports(db, blobs, job_app)
    done = carol.get(f"/api/imports/{record['id']}").json()
    assert done["status"] == "done", done
    print(done["report"])
    assert len(queued) == 4

    again = exported(
        carol, job_app, engine, blobs, settings, tmp_path / "again", trash=True
    )
    after = database(again[0], tmp_path / "again")
    mine = next(o["id"] for o in rows(after, "owners"))
    owners = {o["id"]: "owner" for o in rows(before, "owners")} | {mine: "owner"}
    want, got = normalized(before, owners), normalized(after, owners)
    for table in want:
        assert got[table] == want[table], table
    before.close()
    after.close()


def plainly(record: dict[str, Any]) -> dict[str, Any]:
    """Every group of the export into the person's library, without a
    holding collection (1d of docs/import-mapping.md)."""
    return {
        owner["id"]: {"action": "library"}
        for owner in record["choices"]["owners"]
        if owner["kind"] == "group"
    }


def start(
    person: Person, record: dict[str, Any], body: dict[str, Any] | None = None
) -> httpx2.Response:
    """Start an import waiting for choices: by default everything into the
    person's library (``plainly``)."""
    return person.post(
        f"/api/imports/{record['id']}/start",
        json=body if body is not None else {"owners": plainly(record)},
    )


def import_into(
    person: Person, parts: list[Path], body: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = upload_export(person, parts)
    assert response.status_code == 201, response.text
    started = start(person, response.json(), body)
    assert started.status_code == 200, started.text
    result: dict[str, Any] = started.json()
    return result


def finished(
    person: Person, db: Session, blobs: BlobStore, job_app: App, import_id: str
) -> dict[str, Any]:
    run_imports(db, blobs, job_app)
    record: dict[str, Any] = person.get(f"/api/imports/{import_id}").json()
    assert record["status"] == "done", record
    return record


def counts(db: Session) -> dict[str, int]:
    return {
        model.__tablename__: db.scalar(select(func.count()).select_from(model)) or 0
        for model in (
            Item,
            Version,
            Identifier,
            File,
            Tag,
            ItemTag,
            Collection,
            CollectionItem,
            Note,
            NoteItem,
            CollectionNote,
            ItemReference,
            Favourite,
            PinnedCollection,
        )
    }


def test_importing_twice_adds_nothing(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
) -> None:
    rich = build(client, db)
    parts = exported(rich.ada, job_app, engine, blobs, settings, tmp_path, trash=True)
    before = counts(db)
    for _ in range(2):
        record = import_into(rich.ada, parts)
        report = finished(rich.ada, db, blobs, job_app, record["id"])["report"]
        assert report["added"] == 0 and report["found"] == 5
        assert report["files"] == report["notes"] == report["collections"] == 0
        assert report["problems"] == [] and report["missing_files"] == []
        db.expire_all()
        assert counts(db) == before


def test_owners_go_where_the_person_chooses(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
) -> None:
    rich = build(client, db)
    parts = exported(rich.ada, job_app, engine, blobs, settings, tmp_path)
    erin = Person(client, db, "erin")
    rich.bob.put(f"/api/groups/{rich.lab['id']}/members/{erin.id}", {"role": "member"})
    rich.bob.put(f"/api/groups/{rich.uni['id']}/members/{erin.id}", {"role": "reader"})
    record = upload_export(erin, parts).json()
    owners = {o["name"]: o for o in record["choices"]["owners"]}
    # The same group here is offered, never chosen by itself.
    assert owners["Uni/QCode Lab"]["suggestions"] == [
        {
            "library_id": str(rich.ids["lab"]),
            "name": "Uni/QCode Lab",
            "likeness": "same",
        }
    ]
    assert owners["Uni"]["suggestions"] == []  # a reader may not add there
    assert owners["Me"]["items"] == 2 and owners["Me"]["notes"] == 2
    lab_key, uni_key = owners["Uni/QCode Lab"]["id"], owners["Uni"]["id"]

    def choose(owners: dict[str, Any]) -> int:
        return start(erin, record, {"owners": owners}).status_code

    into = "into"
    assert (
        choose({uni_key: {"action": into, "library_id": str(rich.ids["uni"])}}) == 403
    )
    assert (
        choose({uni_key: {"action": into, "library_id": str(rich.ids["mine"])}}) == 404
    )
    assert choose({"nobody": {"action": "library"}}) == 422
    assert start(rich.ada, record, {}).status_code == 404
    response = start(
        erin,
        record,
        {
            "owners": {
                lab_key: {"action": into, "library_id": str(rich.ids["lab"])},
                uni_key: {"action": "library"},
            }
        },
    )
    assert response.status_code == 200
    assert start(erin, record, {}).status_code == 409
    report = finished(erin, db, blobs, job_app, record["id"])["report"]
    # The group's papers she sees are found; ada's private ones are new
    # (with new ids: those are taken by papers she does not see).
    assert (report["added"], report["found"]) == (2, 2)
    db.expire_all()
    erins = db.scalars(
        select(Item)
        .join(Library, Library.id == Item.library_id)
        .where(Library.user_id == uuid.UUID(erin.id))
    ).all()
    assert sorted(i.title for i in erins) == [
        "Old notes on rain",
        "Radar gaps over the Alps",
    ]
    assert all(i.id not in (rich.ids["radar"], rich.ids["old"]) for i in erins)
    # Ada's notes are hers now; the lab's note was found.
    assert (
        db.scalar(
            select(func.count())
            .select_from(Note)
            .where(Note.text == "Lab meeting: qubits")
        )
        == 1
    )
    # Her private tag on the lab paper ("mine", a private one of ada's)
    # went to erin's own tags; the lab's collection kept the paper once.
    lab_paper = db.get_one(Item, rich.ids["lab_paper"])
    assert sorted(link.tag.name for link in lab_paper.tag_links) == [
        "bob only",
        "lab topic",
        "mine",
        "mine",
    ]
    assert [
        r.name
        for r in db.scalars(
            select(Collection).where(Collection.library_id == rich.ids["lab"])
        )
    ] == ["Lab reading"]


def test_waiting_imports_can_be_dropped(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
) -> None:
    rich = build(client, db)
    parts = exported(rich.ada, job_app, engine, blobs, settings, tmp_path)
    record = upload_export(rich.ada, parts).json()
    sha = db.get_one(Import, uuid.UUID(record["id"])).blob_sha256
    assert sha is not None and blobs.exists(sha)
    assert rich.bob.delete(f"/api/imports/{record['id']}").status_code == 404
    assert rich.ada.delete(f"/api/imports/{record['id']}").status_code == 204
    assert not blobs.exists(sha) and db.get(Blob, sha) is None
    assert rich.ada.get("/api/imports").json() == []
    # A running one stays.
    record = import_into(rich.ada, parts)
    assert rich.ada.delete(f"/api/imports/{record['id']}").status_code == 409
    finished(rich.ada, db, blobs, job_app, record["id"])
    assert rich.ada.delete(f"/api/imports/{record['id']}").status_code == 204


def in_parts(db: Session, blobs: BlobStore, rich: Rich, folder: Path) -> list[Path]:
    """Ada's export in three parts: the database; three files; a large one."""
    item = rich.ada.add("Big data")
    big = bytes(range(256)) * 40
    upload(rich.ada, uuid.UUID(item["id"]), "big.bin", big, "application/zip", "main")
    access = Access.of(db, db.get_one(User, uuid.UUID(rich.ada.id)))
    folder.mkdir()
    written = export.write_export(
        db,
        blobs,
        access,
        export.Options(),
        folder,
        export_id=uuid.uuid4(),
        part_limit=9000,
    )
    db.rollback()
    assert [p.files for p in written.parts] == [0, 3, 1]
    return [folder / part.name for part in written.parts]


def on_a_new_server(db: Session, engine: Engine, client: TestClient) -> Person:
    db.rollback()
    empty_database(engine)
    db.expire_all()
    return Person(client, db, "carol")


def test_parts_together_and_one_added_later(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    tmp_path: Path,
) -> None:
    rich = build(client, db)
    one, two, three = in_parts(db, blobs, rich, tmp_path / "parts")
    carol = on_a_new_server(db, engine, client)
    # Any order; part 2 missing first.
    record = upload_export(carol, [three, one]).json()
    assert record["filename"] == one.name
    choices = record["choices"]
    assert choices["uploaded"] == [1, 3] and choices["parts"] == 3
    assert choices["missing"] == [{"part": 2, "name": two.name, "files": 3}]
    added = carol.client.post(
        f"/api/imports/{record['id']}/parts",
        headers=carol.headers,
        files=[("parts", (two.name, two.read_bytes(), "application/zip"))],
    )
    assert added.status_code == 200, added.text
    assert added.json()["choices"]["missing"] == []
    assert len(db.get_one(Import, uuid.UUID(record["id"])).parts) == 2
    start(carol, record)
    report = finished(carol, db, blobs, job_app, record["id"])["report"]
    assert report["files"] == 4 and report["problems"] == []
    assert report["missing_files"] == []
    # The uploads are gone with the import.
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ImportPart)) == 0
    stored = set(db.scalars(select(Blob.sha256)))
    assert all(
        hashlib.sha256(p.read_bytes()).digest() not in stored for p in (one, two, three)
    )
    # Waiting no longer: no more parts.
    late = carol.client.post(
        f"/api/imports/{record['id']}/parts",
        headers=carol.headers,
        files=[("parts", (two.name, two.read_bytes(), "application/zip"))],
    )
    assert late.status_code == 409


def test_a_part_missing_is_reported(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    tmp_path: Path,
) -> None:
    rich = build(client, db)
    one, two, three = in_parts(db, blobs, rich, tmp_path / "parts")
    carol = on_a_new_server(db, engine, client)
    record = import_into(carol, [one, three])
    report = finished(carol, db, blobs, job_app, record["id"])["report"]
    assert report["files"] == 1 and report["added"] == 5
    assert report["problems"] == [
        f"Part 2 of 3 was not uploaded ({two.name}): its 3 files are missing."
    ]
    assert sorted(report["missing_files"]) == sorted(
        f"files/{name}"
        for name in (
            "van Gogh 2025 - Radar gaps over the Alps.pdf",
            "van Gogh 2025 - Radar gaps over the Alps (supplementary).csv",
            "Lovelace 1843 - Qubits in the lab.pdf",
        )
    )


def test_parts_that_do_not_belong(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    tmp_path: Path,
) -> None:
    rich = build(client, db)
    one, two, three = in_parts(db, blobs, rich, tmp_path / "first")
    access = Access.of(db, db.get_one(User, uuid.UUID(rich.ada.id)))
    (tmp_path / "second").mkdir()
    other = export.write_export(
        db,
        blobs,
        access,
        export.Options(),
        tmp_path / "second",
        export_id=uuid.uuid4(),
        part_limit=9000,
    )
    db.rollback()
    other_one, other_two = (tmp_path / "second" / p.name for p in other.parts[:2])
    bib = tmp_path / "library.bib"
    bib.write_text("@article{a, title={Rain}}\n")

    # Another export's part, and a file of no export: left out, by name.
    record = upload_export(rich.ada, [one, other_two, bib]).json()
    assert sorted(record["choices"]["refused"]) == ["library.bib", other_two.name]
    assert record["choices"]["uploaded"] == [1]
    # Without part 1, nothing can be read.
    response = upload_export(rich.ada, [two, three])
    assert response.status_code == 422
    assert (
        response.json()["detail"] == f"Part 1 holds the database: add it ({one.name})."
    )
    response = upload_export(rich.ada, [one, other_one])
    assert response.status_code == 422
    assert "different exports" in response.json()["detail"]
    # Several files are only for an export in parts.
    response = upload_export(rich.ada, [bib, bib])
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Choose one file")
    assert len(rich.ada.get("/api/imports").json()) == 1


def rezip(
    source: Path,
    target: Path,
    *,
    replace: dict[str, bytes | None] | None = None,
    sql: list[str] | None = None,
) -> Path:
    """A copy of an export's zip with members replaced (None: left out)
    or its database changed."""
    with zipfile.ZipFile(source) as archive:
        top = archive.namelist()[0].split("/")[0]
        changes = {k.replace("{top}", top): v for k, v in (replace or {}).items()}
        if sql:
            path = target.parent / "changed.sqlite"
            path.write_bytes(archive.read(f"{top}/library.sqlite"))
            changed = sqlite3.connect(path)
            for statement in sql:
                changed.execute(statement)
            changed.commit()
            changed.close()
            changes[f"{top}/library.sqlite"] = path.read_bytes()
            path.unlink()
        with zipfile.ZipFile(target, "w") as out:
            for info in archive.infolist():
                data = changes.pop(info.filename, archive.read(info))
                if data is not None:
                    out.writestr(info, data)
    return target


def test_damaged_files_are_left_out(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
) -> None:
    rich = build(client, db)
    (part,) = exported(rich.ada, job_app, engine, blobs, settings, tmp_path)
    radar = "files/van Gogh 2025 - Radar gaps over the Alps.pdf"
    lab = "files/Lovelace 1843 - Qubits in the lab.pdf"
    # One file's bytes changed in the zip (its checksum fails), another
    # listed with other contents than it has.
    damaged = rezip(
        part,
        tmp_path / "damaged.zip",
        sql=[
            "UPDATE files SET sha256 = '" + "ab" * 32 + "' WHERE filename = 'lab.pdf'"
        ],
    )
    with zipfile.ZipFile(damaged) as archive:
        info = next(i for i in archive.infolist() if i.filename.endswith(radar))
    data = bytearray(damaged.read_bytes())
    start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    data[start + 100] ^= 0xFF
    damaged.write_bytes(bytes(data))
    carol = on_a_new_server(db, engine, client)
    record = import_into(carol, [damaged])
    report = finished(carol, db, blobs, job_app, record["id"])["report"]
    assert report["files"] == 1 and report["added"] == 4
    assert len(report["problems"]) == 2
    assert report["problems"][0].startswith(f"{radar}: damaged in the zip")
    assert report["problems"][1] == (
        f"{lab}: damaged (not the content the export lists); left out"
    )
    db.expire_all()
    assert [f.filename for f in db.scalars(select(File))] == ["data.csv"]


def test_hostile_and_foreign_zips(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rich = build(client, db)
    (part,) = exported(rich.ada, job_app, engine, blobs, settings, tmp_path)
    with zipfile.ZipFile(part) as archive:
        marker = json.loads(archive.read(archive.namelist()[1]))

    def refused(path: Path) -> str:
        response = upload_export(rich.ada, [path])
        assert response.status_code == 422, response.text
        detail: str = response.json()["detail"]
        return detail

    newer = rezip(
        part,
        tmp_path / "newer.zip",
        replace={
            "{top}/part.json": json.dumps({**marker, "format_version": 2}).encode()
        },
    )
    assert "newer paperus (export format 2)" in refused(newer)
    no_database = rezip(
        part, tmp_path / "nodb.zip", replace={"{top}/library.sqlite": None}
    )
    assert refused(no_database) == "nodb.zip has no library.sqlite."
    garbage = rezip(
        part,
        tmp_path / "garbage.zip",
        replace={"{top}/library.sqlite": b"no database" * 200},
    )
    assert refused(garbage) == "library.sqlite is not a SQLite database."
    lacking = rezip(part, tmp_path / "lacking.zip", sql=["DROP TABLE notes"])
    assert (
        refused(lacking) == "library.sqlite has no table notes: not a paperus export."
    )
    future = rezip(
        part, tmp_path / "future.zip", sql=["UPDATE paperus SET format_version = 3"]
    )
    assert "newer paperus (export format 3)" in refused(future)
    other = rezip(
        part,
        tmp_path / "other.zip",
        sql=[f"UPDATE paperus SET export_id = '{uuid.uuid4()}'"],
    )
    assert refused(other) == "Part 1's database belongs to another export."
    unknown = rezip(
        part, tmp_path / "unknown.zip", sql=["UPDATE paperus SET format = 'x'"]
    )
    assert refused(unknown) == "library.sqlite is not a paperus export."
    two_rows = rezip(
        part, tmp_path / "two.zip", sql=["INSERT INTO paperus SELECT * FROM paperus"]
    )
    assert (
        refused(two_rows) == "library.sqlite does not say what it is (table paperus)."
    )
    with monkeypatch.context() as patched:
        patched.setattr(paperus_export, "MAX_DATABASE_BYTES", 10)
        assert "at most" in refused(part)

    # Paths leading out of the zip find nothing; a broken row is reported,
    # the rest comes in.
    tricky = rezip(
        part,
        tmp_path / "tricky.zip",
        sql=[
            "UPDATE files SET path = '../../../etc/passwd' WHERE filename = 'lab.pdf'",
            "UPDATE items SET created_at = 'yesterday' WHERE title = 'Uni handbook'",
            "UPDATE notes SET text = 'Changed' WHERE title = 'Ideas for chapter 2'",
        ],
    )
    carol = on_a_new_server(db, engine, client)
    record = import_into(carol, [tricky])
    report = finished(carol, db, blobs, job_app, record["id"])["report"]
    assert report["missing_files"] == ["../../../etc/passwd"]
    assert report["added"] == 3 and report["files"] == 2
    assert report["problems"] == ["Uni handbook: Invalid isoformat string: 'yesterday'"]
    assert not (tmp_path.parent / "etc").exists()


@pytest.mark.parametrize(
    "left_out",
    ["notes", "tags", "collections", "references", "files", "archived"],
)
def test_any_part_may_be_missing(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
    left_out: str,
) -> None:
    rich = build(client, db)
    parts = exported(
        rich.ada, job_app, engine, blobs, settings, tmp_path, include={left_out: False}
    )
    carol = on_a_new_server(db, engine, client)
    record = import_into(carol, parts)
    report = finished(carol, db, blobs, job_app, record["id"])["report"]
    assert report["problems"] == []
    db.expire_all()
    found = counts(db)
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
        "files": {"files"},
        "archived": set(),
    }[left_out]
    for table, count in found.items():
        assert (count == 0) == (table in empty), (table, count)
    assert found["items"] == (3 if left_out == "archived" else 4)
    if left_out == "files":
        # Listed as missing: Manage → Missing can fetch them later.
        assert len(report["missing_files"]) == 3


def test_through_the_worker(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    fake_ml: FakeML,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The jobs as ``paperus worker`` runs them."""
    context = jobs.WorkerContext(
        engine=engine,
        sessions=make_sessionmaker(engine),
        blobs=blobs,
        http=httpx2.Client(
            transport=httpx2.MockTransport(lambda r: httpx2.Response(404))
        ),
        ml=fake_ml.client(),
        settings=settings,
    )
    monkeypatch.setattr(jobs, "_context", context)

    def work() -> None:
        job_app.run_worker(
            wait=False, install_signal_handlers=False, listen_notify=False
        )

    rich = build(client, db)
    record = rich.ada.post("/api/exports", json={}).json()
    work()
    done = rich.ada.get(f"/api/exports/{record['id']}").json()
    assert done["status"] == "done"
    part = tmp_path / done["parts"][0]["name"]
    part.write_bytes(rich.ada.get(f"/api/exports/{record['id']}/parts/1").content)
    db.get_one(Export, uuid.UUID(record["id"])).expires_at = datetime.now(UTC)
    db.commit()
    job_app.configure_task("paperus:remove_expired_exports").defer(timestamp=0)
    work()
    assert rich.ada.get(f"/api/exports/{record['id']}").json()["status"] == "expired"

    started = import_into(rich.ada, [part])
    work()
    report = rich.ada.get(f"/api/imports/{started['id']}").json()["report"]
    assert report["found"] == 4 and report["added"] == 0


def test_command_line_import_finds_the_other_parts(
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    capsys: pytest.CaptureFixture[str],
    engine: Engine,
) -> None:
    rich = build(client, db)
    one, _, _ = in_parts(db, blobs, rich, tmp_path / "parts")
    carol = on_a_new_server(db, engine, client)
    monkeypatch.setenv("PAPERUS_DATABASE_URL", database_url)
    monkeypatch.setenv("PAPERUS_STORAGE_PATH", str(settings.storage_path))
    (tmp_path / "parts" / "unrelated.zip").write_bytes(b"not a zip")
    with pytest.raises(SystemExit) as exit:
        main(["import", str(one), "--user", "carol"])
    out = capsys.readouterr().out
    assert exit.value.code == 0, out
    assert "5 papers: 5 added, 0 already there; 4 files" in out
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(File)) == 4
    assert carol.get("/api/imports").json()[0]["format"] == "paperus"


def test_papers_already_here_are_found(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
) -> None:
    """By identifier or file, also when the export's ids are not known."""
    rich = build(client, db)
    (part,) = exported(rich.ada, job_app, engine, blobs, settings, tmp_path)
    ids = rich.ids

    def new_id(item: str) -> list[str]:
        fresh, old = str(uuid.uuid4()), str(ids[item])
        return [
            f"UPDATE {table} SET item_id = '{fresh}' WHERE item_id = '{old}'"
            for table in (
                "versions",
                "item_tags",
                "collection_items",
                "note_items",
                "favourites",
                "item_references",
            )
        ] + [f"UPDATE items SET id = '{fresh}' WHERE id = '{old}'"]

    changed = rezip(
        part,
        tmp_path / "changed.zip",
        sql=[
            *new_id("lab_paper"),  # found by its DOI
            *new_id("radar"),  # found by its file
            "UPDATE identifiers SET value = value || '-other'"
            " WHERE value IN ('10.1234/radar', '2401.00001')",
            *new_id("old"),  # nothing to go by: added
            # Shares the lab paper's DOI: found as that one.
            "INSERT INTO identifiers SELECT id || 'x', created_at, "
            f"(SELECT id FROM versions WHERE item_id = '{ids['uni_paper']}'), scheme,"
            " value FROM identifiers WHERE value = '10.5555/qubits'",
        ],
    )
    # One of radar's files is on another paper here: it is added to radar.
    csv = db.scalars(select(File).where(File.filename == "data.csv")).one()
    csv.version_id = db.get_one(Item, ids["old"]).versions[0].id
    db.commit()
    record = import_into(rich.ada, [changed])
    report = finished(rich.ada, db, blobs, job_app, record["id"])["report"]
    assert (report["added"], report["found"]) == (1, 3), report
    assert report["files"] == 1 and report["problems"] == []
    db.expire_all()
    radar = db.get_one(Item, ids["radar"])
    assert sorted(f.filename for v in radar.versions for f in v.files) == [
        "data.csv",
        "radar.pdf",
    ]
    # The uni paper went to the lab paper (the same DOI), not kept apart.
    uni = db.get_one(Item, ids["uni_paper"])
    assert all(i.value != "10.5555/qubits" for v in uni.versions for i in v.identifiers)


def test_odd_values_in_the_database(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
) -> None:
    """What another tool may have written: unknown kinds, broken rules,
    links to nothing; read as far as it goes."""
    rich = build(client, db)
    (part,) = exported(rich.ada, job_app, engine, blobs, settings, tmp_path)
    ids = rich.ids
    odd = rezip(
        part,
        tmp_path / "odd.zip",
        sql=[
            "UPDATE versions SET kind = 'weird', metadata_source = 'elsewhere'",
            "UPDATE identifiers SET scheme = 'isbnx' WHERE scheme = 'arxiv'",
            "UPDATE collections SET rules = '[1]' WHERE name = 'Physics'",
            f"UPDATE collections SET parent_id = '{ids['smart']}'"
            " WHERE name = 'Chapter 1'",
            "UPDATE tags SET color = 'plaid' WHERE name = 'to read'",
            "UPDATE item_tags SET source = 'magic'",
            "UPDATE users SET id = 'not an id' WHERE username = 'bob'",
            "UPDATE note_items SET page = 0",
            "UPDATE items SET overrides = '[1]' WHERE title = 'Uni handbook'",
            "UPDATE items SET title = X'4142' WHERE title = 'Old notes on rain'",
            "INSERT INTO item_tags SELECT item_id, 'nothing', source, added_by,"
            " created_at FROM item_tags LIMIT 1",
            "INSERT INTO collection_items SELECT 'nothing', item_id, added_by,"
            " created_at FROM collection_items LIMIT 1",
            "INSERT INTO note_items SELECT note_id, 'nothing', page, added_by,"
            " created_at FROM note_items LIMIT 1",
            "UPDATE paperus SET options = 'not json', server_url = NULL",
        ],
    )
    carol = on_a_new_server(db, engine, client)
    record = upload_export(carol, [odd]).json()
    assert record["choices"]["options"] == {}
    start(carol, record)
    report = finished(carol, db, blobs, job_app, record["id"])["report"]
    assert report["added"] == 2
    assert sorted(report["problems"]) == [
        "Uni handbook: not a JSON object",
        "b'AB': not text: b'AB'",
    ]
    db.expire_all()
    kinds = {v.kind for v in db.scalars(select(Version))}
    assert kinds == {"other"}
    assert {i.scheme for i in db.scalars(select(Identifier))} == {"doi"}
    collections = {c.name: c for c in db.scalars(select(Collection))}
    assert collections["Physics"].rules == {}
    assert collections["Chapter 1"].parent_id is None
    assert collections["Thesis"].parent_id is None
    tag = db.scalars(select(Tag).where(Tag.name == "to read")).one()
    assert tag.color == "gray"
    assert {link.source for link in db.scalars(select(ItemTag))} == {"manual"}
    assert {link.page for link in db.scalars(select(NoteItem))} == {None}


def test_files_too_large_here(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
) -> None:
    rich = build(client, db)
    (part,) = exported(rich.ada, job_app, engine, blobs, settings, tmp_path)
    carol = on_a_new_server(db, engine, client)
    record = upload_export(carol, [part]).json()
    start(carol, record)
    row = db.get_one(Import, uuid.UUID(record["id"]))
    assert row.blob_sha256 is not None
    with blobs.local_file(row.blob_sha256) as path:
        run_import(db, blobs, row, path=path, max_file_bytes=100)
    report = carol.get(f"/api/imports/{record['id']}").json()["report"]
    assert report["files"] == 1  # the small csv
    assert sorted(report["problems"]) == [
        "files/Lovelace 1843 - Qubits in the lab.pdf: too large",
        "files/van Gogh 2025 - Radar gaps over the Alps.pdf: too large",
    ]


def test_parts_are_recognised(tmp_path: Path) -> None:
    def marker(name: str, **members: bytes) -> paperus_export.Marker | None:
        path = tmp_path / name
        path.write_bytes(zip_bytes(**members))
        return paperus_export.read_marker(paperus_export.Upload(path, name))

    good = {
        "format": "paperus-export",
        "format_version": 1,
        "export": str(uuid.uuid4()),
        "name": "paperus-export-2026-11-07",
        "part": 2,
        "parts": 3,
    }

    def part(**changes: object) -> bytes:
        return json.dumps({**good, **changes}).encode()

    found = marker("a.zip", **{"x/part.json": part()})
    assert found is not None and (found.part, found.parts) == (2, 3)
    not_zip = tmp_path / "plain.bib"
    not_zip.write_text("@article{a}")
    assert paperus_export.read_marker(paperus_export.Upload(not_zip, "x")) is None
    assert marker("b.zip", **{"part.json": part()}) is None  # not in a folder
    assert marker("c.zip", **{"x/part.json": b"{broken"}) is None
    assert marker("d.zip", **{"x/part.json": b"[1]"}) is None
    assert marker("e.zip", **{"x/part.json": part(format="zotero")}) is None
    assert marker("f.zip", **{"x/part.json": part(part=4)}) is None
    assert marker("g.zip", **{"x/part.json": part(name="../up")}) is None
    assert marker("h.zip", **{"x/part.json": part(export="nope")}) is None
    assert marker("i.zip", **{"x/part.json": b" " * 70_000}) is None
    with pytest.raises(paperus_export.NotAnExport, match="newer paperus"):
        marker("j.zip", **{"x/part.json": part(format_version="2")})
    plain = tmp_path / "k.zip"
    plain.write_bytes(zip_bytes(**{"x/notes.txt": b"hello"}))
    with (
        pytest.raises(paperus_export.NotAnExport, match="no part of a paperus"),
        paperus_export.opened([paperus_export.Upload(plain, "k.zip")], tmp_path),
    ):
        pass


def test_a_damaged_database(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
) -> None:
    rich = build(client, db)
    (part,) = exported(rich.ada, job_app, engine, blobs, settings, tmp_path)
    with zipfile.ZipFile(part) as archive:
        info = archive.infolist()[0]
    data = bytearray(part.read_bytes())
    start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    data[start + 50] ^= 0xFF
    broken = tmp_path / "broken.zip"
    broken.write_bytes(bytes(data))
    response = upload_export(rich.ada, [broken])
    assert response.status_code == 422
    assert response.json()["detail"].startswith("library.sqlite could not be unpacked")
    odd = rezip(
        part, tmp_path / "odd.zip", sql=["ALTER TABLE files DROP COLUMN included"]
    )
    response = upload_export(rich.ada, [odd])
    assert response.status_code == 422
    assert response.json()["detail"].startswith("library.sqlite could not be read")
    # A part that is too large: nothing is kept.
    before = db.scalar(select(func.count()).select_from(Blob))
    settings.max_import_bytes = 2000
    response = upload_export(rich.ada, [part, part])
    assert response.status_code == 413
    assert db.scalar(select(func.count()).select_from(Blob)) == before
    # A part added later that is not one.
    settings.max_import_bytes = 10**9
    record = upload_export(rich.ada, [part]).json()
    newer = rezip(
        part,
        tmp_path / "newer.zip",
        replace={
            "{top}/part.json": json.dumps(
                {"format": "paperus-export", "format_version": 9}
            ).encode()
        },
    )
    added = rich.ada.client.post(
        f"/api/imports/{record['id']}/parts",
        headers=rich.ada.headers,
        files=[("parts", ("newer.zip", newer.read_bytes(), "application/zip"))],
    )
    assert added.status_code == 422
    assert db.scalar(select(func.count()).select_from(Blob)) == (before or 0) + 1


def test_the_command_line_looks_for_parts_beside(tmp_path: Path) -> None:
    def part(name: str, **changes: object) -> Path:
        marker = {
            "format": "paperus-export",
            "format_version": 1,
            "export": "01a1b6c2-0000-7000-8000-000000000001",
            "name": "paperus-export-2026-11-07",
            "part": 1,
            "parts": 2,
            **changes,
        }
        path = tmp_path / name
        path.write_bytes(zip_bytes(**{"x/part.json": json.dumps(marker).encode()}))
        return path

    first = part("one.zip")
    second = part("two.zip", part=2)
    part("newer.zip", format_version=7)
    part("other.zip", export="01a1b6c2-0000-7000-8000-000000000002", part=2)
    assert other_parts(first) == [(second, "two.zip")]
    assert other_parts(part("alone.zip", parts=1)) == []
    assert other_parts(tmp_path / "newer.zip") == []
