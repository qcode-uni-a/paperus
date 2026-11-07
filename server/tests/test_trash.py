"""Emptying the trash: for good, by age or by hand, and what nothing uses."""

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from paperus import trash
from paperus.config import Settings
from paperus.models import Blob, Item, Note
from paperus.storage import BlobStore, FilesystemStore
from tests.people import Person, group

PDF = b"%PDF-1.7\n" + b"x" * 3000 + b"\n%%EOF\n"
OTHER = b"%PDF-1.7\n" + b"y" * 3000 + b"\n%%EOF\n"


def upload(person: Person, item: str, data: bytes) -> str:
    response = person.post(
        f"/api/items/{item}/files", files={"upload": ("p.pdf", data, "application/pdf")}
    )
    assert response.status_code == 201, response.text
    sha: str = response.json()["sha256"]
    return sha


def test_empty_by_age(client: TestClient, db: Session, blobs: BlobStore) -> None:
    ada = Person(client, db, "ada")
    old, fresh, keep = ada.add("Old"), ada.add("Fresh"), ada.add("Keep")
    upload(ada, old["id"], PDF)
    upload(ada, keep["id"], PDF)  # the same contents: stays stored
    only_old = upload(ada, fresh["id"], OTHER)
    note = ada.note("Old note")
    for path in (f"/api/items/{old['id']}", f"/api/items/{fresh['id']}"):
        ada.delete(path)
    ada.delete(f"/api/notes/{note['id']}")
    long_ago = datetime.now(UTC) - timedelta(days=40)
    db.execute(update(Item).where(Item.id == old["id"]).values(deleted_at=long_ago))
    db.execute(update(Note).values(deleted_at=long_ago))
    db.commit()

    done = trash.empty(db, blobs, before=datetime.now(UTC) - timedelta(days=30))
    assert (done.items, done.notes, done.blobs) == (1, 1, 0)
    assert ada.get(f"/api/items/{old['id']}").status_code == 404
    assert ada.get(f"/api/items/{fresh['id']}").json()["deleted_at"]
    # Everything left in the trash: the fresh paper's contents go too.
    done = trash.empty(db, blobs)
    assert (done.items, done.blobs) == (1, 1)
    assert not blobs.exists(bytes.fromhex(only_old))
    assert db.scalar(select(func.count()).select_from(Blob)) == 1


def test_empty_by_hand_only_what_one_may_change(
    client: TestClient, db: Session
) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    shared = ada.add("Group paper", chair["library_id"])
    mine = bob.add("Bob's")
    ada.delete(f"/api/items/{shared['id']}")
    bob.delete(f"/api/items/{mine['id']}")
    emptied = bob.delete("/api/trash").json()
    assert emptied["items"] == 1  # only his own; he reads the group's
    assert ada.get(f"/api/items/{shared['id']}").json()["deleted_at"]
    assert ada.delete("/api/trash").json()["items"] == 1


def test_installation_settings(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    config = root.get("/api/admin/config").json()
    assert config["max_upload_mb"] == 512 and config["trash_days"] is None
    response = root.put(
        "/api/admin/config",
        json={
            **config,
            "max_upload_mb": 1,
            "contact_email": "library@uni.example",
            "public_url": "https://papers.uni.example/",
            "trash_days": 30,
            "log_level": "debug",
        },
    )
    assert response.status_code == 200, response.text
    saved = root.get("/api/admin/config").json()
    assert saved["public_url"] == "https://papers.uni.example/"
    app = client.app
    assert isinstance(app, FastAPI)
    agent = app.state.http.headers["User-Agent"]
    assert agent.endswith("(mailto:library@uni.example)")
    # The upload limit applies at once.
    item = root.add("Big")
    big = b"%PDF-1.7\n" + b"x" * (2 * 2**20)
    response = root.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("big.pdf", big, "application/pdf")},
    )
    assert response.status_code == 413
    bad = root.put("/api/admin/config", json={**saved, "contact_email": "nope"})
    assert bad.status_code == 422


def test_storage_usage(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    item = root.add("A paper")
    upload(root, item["id"], PDF)
    space = root.get("/api/storage").json()
    assert space["library_bytes"] == len(PDF)
    assert space["disk_total"] > space["disk_free"] > 0
    stats = root.get("/api/admin/stats").json()["storage"]
    assert stats["library_bytes"] == len(PDF)
    assert stats["disk"]["total"] == space["disk_total"]


class UndeletableStore(FilesystemStore):
    """A store whose files cannot be removed (e.g. a read-only mount)."""

    def delete(self, sha256: bytes) -> None:
        raise PermissionError(sha256.hex())


def test_contents_that_cannot_be_removed(
    client: TestClient, db: Session, settings: Settings
) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Old")
    sha = upload(ada, paper["id"], PDF)
    ada.delete(f"/api/items/{paper['id']}")
    store = UndeletableStore(settings.storage_path)
    done = trash.empty(db, store)
    # The row goes (an integrity check finds the file); emptying goes on.
    assert (done.items, done.blobs, done.bytes) == (1, 1, len(PDF))
    assert db.scalar(select(func.count()).select_from(Blob)) == 0
    assert store.exists(bytes.fromhex(sha))
