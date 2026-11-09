"""A rich library to export and import again (tests/test_export*.py,
test_import_export.py): two people, a group with a sub-group, papers with
versions, files, tags of every source, nested and smart collections, notes,
favourites, the archive, the trash, manual edits and reference lists."""

import io
import sqlite3
import uuid
import zipfile
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from paperus import authors, export, library, notes, organize
from paperus.config import Settings
from paperus.db import make_sessionmaker
from paperus.identifiers import Scheme
from paperus.importing.run import run_import
from paperus.models import (
    Collection,
    CollectionNote,
    Favourite,
    Import,
    Item,
    ItemReference,
    Library,
    MetadataSource,
    NoteItem,
    PinnedCollection,
    TagSource,
    VersionKind,
)
from paperus.storage import BlobStore
from tests.pdfs import make_pdf
from tests.people import Person, group


@dataclass
class Rich:
    ada: Person
    bob: Person
    root: Person
    uni: dict[str, Any]
    lab: dict[str, Any]
    ids: dict[str, uuid.UUID] = field(default_factory=dict)
    """Names of things → their ids."""
    pdfs: dict[str, bytes] = field(default_factory=dict)


def _library_of(db: Session, person: Person) -> uuid.UUID:
    return db.scalars(
        select(Library.id).where(Library.user_id == uuid.UUID(person.id))
    ).one()


def upload(
    person: Person, item_id: uuid.UUID, name: str, data: bytes, media: str, role: str
) -> dict[str, Any]:
    response = person.client.post(
        f"/api/items/{item_id}/files",
        headers=person.headers,
        files={"upload": (name, data, media)},
        data={"role": role},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def build(client: TestClient, db: Session) -> Rich:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    bob = Person(client, db, "bob")
    uni = group(root, "Uni", bob)
    lab = group(bob, "QCode Lab", bob, parent=uni["id"])
    for group_id, role in ((uni["id"], "reader"), (lab["id"], "member")):
        response = bob.put(f"/api/groups/{group_id}/members/{ada.id}", {"role": role})
        assert response.status_code in (200, 204), response.text
    rich = Rich(ada, bob, root, uni, lab)
    mine = _library_of(db, ada)
    theirs = _library_of(db, bob)
    lab_library = uuid.UUID(lab["library_id"])
    uni_library = uuid.UUID(uni["library_id"])
    ada_id, bob_id = uuid.UUID(ada.id), uuid.UUID(bob.id)
    rich.ids |= {"mine": mine, "lab": lab_library, "uni": uni_library}

    # Ada's paper: a preprint and its published version, manual edits.
    radar = library.create_item(
        db,
        mine,
        kind=VersionKind.PREPRINT,
        label="v2",
        csl={
            "type": "article",
            "title": "Radar gaps over the Alps",
            "author": [{"family": "van Gogh", "given": "Vincent"}],
            "issued": {"date-parts": [[2024]]},
        },
        source=MetadataSource.LOOKUP,
        identifiers=[(Scheme.ARXIV, "2401.00001")],
        added_by=ada_id,
    )
    published = library.add_version(
        db,
        radar,
        kind=VersionKind.PUBLISHED,
        label=None,
        csl={
            "type": "article-journal",
            "title": "Radar gaps over the Alps",
            "author": [{"family": "van Gogh", "given": "Vincent"}],
            "container-title": "Journal of Weather",
            "issued": {"date-parts": [[2025]]},
            "DOI": "10.1234/radar",
        },
        source=MetadataSource.MANUAL,
        identifiers=[(Scheme.DOI, "10.1234/radar")],
        created_by=ada_id,
    )
    library.set_overrides(radar, {"title-short": "Radar", "note": None})
    radar.file_wanted = True
    db.add(
        ItemReference(
            item_id=radar.id,
            position=1,
            text="A. Lovelace, Notes (1843).",
            authors="Lovelace",
            year=1843,
        )
    )
    db.add(
        ItemReference(
            item_id=radar.id,
            position=2,
            text="B. Babbage, Engine, doi:10.1/engine",
            doi="10.1/engine",
            arxiv=None,
        )
    )
    radar.references_source = "crossref"
    radar.references_checked_at = datetime.now(UTC)
    # Not cited: kept for good.
    old = library.create_item(
        db,
        mine,
        kind=VersionKind.OTHER,
        label=None,
        csl={"type": "document", "title": "Old notes on rain"},
        source=MetadataSource.MANUAL,
        identifiers=[],
        added_by=ada_id,
    )
    old.archived_at = datetime.now(UTC)
    trashed = library.create_item(
        db,
        mine,
        kind=VersionKind.OTHER,
        label=None,
        csl={"type": "document", "title": "Trashed draft"},
        source=MetadataSource.MANUAL,
        identifiers=[],
        added_by=ada_id,
    )
    lab_paper = library.create_item(
        db,
        lab_library,
        kind=VersionKind.PUBLISHED,
        label=None,
        csl={
            "type": "article-journal",
            "title": "Qubits in the lab",
            "author": [{"family": "Lovelace", "given": "Ada"}],
            "issued": {"date-parts": [[1843]]},
        },
        source=MetadataSource.IMPORT,
        identifiers=[(Scheme.DOI, "10.5555/qubits")],
        added_by=bob_id,
    )
    uni_paper = library.create_item(
        db,
        uni_library,
        kind=VersionKind.PUBLISHED,
        label=None,
        csl={"type": "book", "title": "Uni handbook"},
        source=MetadataSource.MANUAL,
        identifiers=[],
        added_by=bob_id,
    )
    secret = library.create_item(
        db,
        theirs,
        kind=VersionKind.OTHER,
        label=None,
        csl={"type": "document", "title": "Bob's secret plan"},
        source=MetadataSource.MANUAL,
        identifiers=[(Scheme.DOI, "10.9999/secret")],
        added_by=bob_id,
    )
    db.commit()
    rich.ids |= {
        "radar": radar.id,
        "published": published.id,
        "old": old.id,
        "trashed": trashed.id,
        "lab_paper": lab_paper.id,
        "uni_paper": uni_paper.id,
        "secret": secret.id,
    }

    # Files, by upload (as people add them).
    rich.pdfs["radar"] = make_pdf([["Radar gaps over the Alps", "Page one"]])
    rich.pdfs["lab"] = make_pdf([["Qubits in the lab"]])
    rich.pdfs["secret"] = make_pdf([["Bob's secret plan"]])
    radar_pdf = upload(
        ada, radar.id, "radar.pdf", rich.pdfs["radar"], "application/pdf", "main"
    )
    # Ada's annotations of it, shown to those who may read the paper.
    for mark in (
        {
            "kind": "highlight",
            "page_index": 0,
            "position": {"rects": [[72, 700, 200, 712]]},
            "color": "#5fb236",
            "text": "Radar gaps",
            "comment": "Key",
            "tags": ["method"],
        },
        {
            "kind": "ink",
            "page_index": 0,
            "position": {"paths": [[1, 2, 3, 4]], "width": 2},
        },
    ):
        made = ada.post(f"/api/files/{radar_pdf['id']}/annotations", mark)
        assert made.status_code == 201, made.text
    ada.put(f"/api/items/{radar.id}/annotation-sharing", {"shared": True})
    upload(ada, radar.id, "data.csv", b"x,y\n1,2\n", "text/csv", "supplementary")
    upload(bob, lab_paper.id, "lab.pdf", rich.pdfs["lab"], "application/pdf", "main")
    upload(bob, secret.id, "s.pdf", rich.pdfs["secret"], "application/pdf", "main")
    trashed_file = upload(
        ada, trashed.id, "draft.txt", b"draft text", "text/plain", "main"
    )
    rich.ids["trashed_file"] = uuid.UUID(trashed_file["id"])
    db.expire_all()
    library.trash(db.get_one(Item, trashed.id), ada_id)

    # Tags of every source, private and the group's.
    radar = db.get_one(Item, radar.id)
    lab_paper = db.get_one(Item, lab_paper.id)
    secret = db.get_one(Item, secret.id)
    to_read = organize.tag_item(db, radar, "to read", library_id=mine, user_id=ada_id)
    physics = organize.tag_item(
        db, radar, "physics", library_id=mine, source=TagSource.AUTOMATIC
    )
    organize.tag_item(
        db, radar, "suggested", library_id=mine, source=TagSource.AI, user_id=ada_id
    )
    topic = organize.tag_item(
        db, lab_paper, "lab topic", library_id=lab_library, user_id=bob_id
    )
    organize.tag_item(db, lab_paper, "mine", library_id=mine, user_id=ada_id)
    organize.tag_item(db, lab_paper, "bob only", library_id=theirs, user_id=bob_id)
    organize.tag_item(db, secret, "secret tag", library_id=theirs, user_id=bob_id)
    to_read.color = "red"
    to_read.description = "Next week"
    db.flush()
    rich.ids |= {"to_read": to_read.id, "physics": physics.id, "topic": topic.id}

    # Collections: nested private ones (also holding the group's paper), a
    # group's, a smart one, bob's private one.
    thesis = Collection(library_id=mine, name="Thesis", created_by=ada_id, change=0)
    db.add(thesis)
    db.flush()
    chapter = Collection(
        library_id=mine,
        name="Chapter 1",
        parent_id=thesis.id,
        created_by=ada_id,
        change=0,
    )
    reading = Collection(
        library_id=lab_library, name="Lab reading", created_by=bob_id, change=0
    )
    smart = Collection(
        library_id=mine,
        name="Physics",
        rules={"tags_any": [str(physics.id)], "owners": [str(mine)]},
        created_by=ada_id,
        change=0,
    )
    hidden = Collection(library_id=theirs, name="Bob's", change=0)
    db.add_all([chapter, reading, smart, hidden])
    db.flush()
    organize.add_to_collection(db, chapter, [radar.id, lab_paper.id], ada_id)
    organize.add_to_collection(db, reading, [lab_paper.id], bob_id)
    organize.add_to_collection(db, hidden, [lab_paper.id], bob_id)
    rich.ids |= {
        "thesis": thesis.id,
        "chapter": chapter.id,
        "reading": reading.id,
        "smart": smart.id,
        "hidden": hidden.id,
    }

    # Notes: on a paper at a page and in a collection; standalone; the
    # group's; bob's private one on the group's paper.
    note = notes.create(db, mine, "# Reading radar\nGood figures.", ada_id)
    note.item_links.append(NoteItem(item_id=radar.id, page=2, added_by=ada_id))
    db.flush()
    organize_note(db, chapter, note.id, ada_id)
    standalone = notes.create(db, mine, "Ideas for chapter 2", ada_id)
    lab_note = notes.create(db, lab_library, "Lab meeting: qubits", bob_id)
    lab_note.item_links.append(NoteItem(item_id=lab_paper.id, added_by=bob_id))
    bobs = notes.create(db, theirs, "Bob's private thoughts", bob_id)
    bobs.item_links.append(NoteItem(item_id=lab_paper.id, added_by=bob_id))
    rich.ids |= {
        "note": note.id,
        "standalone": standalone.id,
        "lab_note": lab_note.id,
        "bobs_note": bobs.id,
    }

    # Ada's view: a star and a pinned collection; bob's star.
    db.add_all(
        [
            Favourite(user_id=ada_id, item_id=radar.id),
            Favourite(user_id=bob_id, item_id=lab_paper.id),
            PinnedCollection(user_id=ada_id, collection_id=thesis.id),
            PinnedCollection(user_id=bob_id, collection_id=reading.id),
        ]
    )
    db.commit()
    # Its authors as people (the background job, by hand here; it loaded
    # the papers into this session, which the tests change behind it).
    authors.link_waiting(db)
    db.expire_all()
    return rich


def organize_note(
    db: Session, collection: Collection, note_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    db.add(
        CollectionNote(collection_id=collection.id, note_id=note_id, added_by=user_id)
    )
    db.flush()


def run_exports(
    job_app: App, engine: Engine, blobs: BlobStore, settings: Settings
) -> int:
    """Run the queued exports as the worker would; how many."""
    assert isinstance(job_app.connector, InMemoryConnector)
    ran = 0
    for key, job in list(job_app.connector.jobs.items()):
        if job["task_name"] != "paperus:export_library":
            continue
        export.run(
            make_sessionmaker(engine),
            blobs,
            settings,
            uuid.UUID(job["args"]["export_id"]),
        )
        del job_app.connector.jobs[key]
        ran += 1
    return ran


def exported(
    person: Person,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    folder: Path,
    **options: object,
) -> list[Path]:
    """Export through the API, run the job, download every part."""
    response = person.post("/api/exports", json=options)
    assert response.status_code == 201, response.text
    export_id = response.json()["id"]
    assert run_exports(job_app, engine, blobs, settings) == 1
    record = person.get(f"/api/exports/{export_id}").json()
    assert record["status"] == "done", record
    paths = []
    folder.mkdir(parents=True, exist_ok=True)
    for part in record["parts"]:
        response = person.get(f"/api/exports/{export_id}/parts/{part['part']}")
        assert response.status_code == 200
        path = folder / part["name"]
        path.write_bytes(response.content)
        paths.append(path)
    return paths


def database(part1: Path, folder: Path) -> sqlite3.Connection:
    """library.sqlite out of part 1, opened."""
    with zipfile.ZipFile(part1) as archive:
        name = next(n for n in archive.namelist() if n.endswith("/library.sqlite"))
        target = folder / "library.sqlite"
        target.write_bytes(archive.read(name))
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    return connection


def rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


def zip_bytes(**members: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def run_imports(db: Session, blobs: BlobStore, job_app: App) -> list[str]:
    """Run the queued imports as the worker does (with all their parts);
    the files they queued for reading."""
    assert isinstance(job_app.connector, InMemoryConnector)
    queued: list[str] = []
    for key, job in list(job_app.connector.jobs.items()):
        if job["task_name"] != "paperus:import_library":
            continue
        del job_app.connector.jobs[key]
        record = db.get(Import, uuid.UUID(job["args"]["import_id"]))
        assert record is not None and record.blob_sha256 is not None
        with ExitStack() as stack:
            path = stack.enter_context(blobs.local_file(record.blob_sha256))
            parts = [
                (stack.enter_context(blobs.local_file(p.blob_sha256)), p.filename)
                for p in record.parts
                if p.blob_sha256 is not None
            ]
            run_import(
                db,
                blobs,
                record,
                path=path,
                parts=parts,
                max_file_bytes=10_000_000,
                file_added=lambda file_id: queued.append(str(file_id)),
            )
    return queued


def empty_database(engine: Engine) -> None:
    """Everything gone, as on a new server (the stored files stay)."""
    with engine.begin() as connection:
        tables = connection.scalars(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                " AND tablename NOT IN ('alembic_version', 'change_counters')"
            )
        ).all()
        connection.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))


def upload_export(
    person: Person, paths: list[Path], library_id: str | None = None
) -> httpx2.Response:
    files = [("upload", (paths[0].name, paths[0].read_bytes(), "application/zip"))]
    files += [("parts", (p.name, p.read_bytes(), "application/zip")) for p in paths[1:]]
    return person.client.post(
        "/api/imports",
        headers=person.headers,
        files=files,
        data={"library_id": library_id} if library_id else {},
    )
