"""A folder of stored files out of reach (a network share not mounted):
new contents wait in a local incoming folder, readable, and move over when
it is back (``storage.FilesystemStore``, ``jobs.move_incoming``)."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus import storage
from paperus.jobs import claim_storage
from paperus.storage import FilesystemStore
from tests.people import Person

PDF = b"%PDF-1.7\n" + b"x" * 3000 + b"\n%%EOF\n"


def test_waits_while_out_of_reach_then_moves(tmp_path: Path) -> None:
    share, incoming = tmp_path / "share", tmp_path / "incoming"
    blobs = FilesystemStore(share, incoming)
    # Not ours yet (no marker): out of reach, so new contents wait.
    assert not blobs.reachable()
    sha = blobs.put([b"written offline"], max_size=1 << 20).sha256
    assert blobs.path(sha).is_relative_to(incoming)
    assert b"".join(blobs.iter_bytes(sha)) == b"written offline"
    assert blobs.move_incoming() == 0
    assert [s for s, _, _ in blobs.iter_stored()] == [sha]

    # A new library's folder: claimed, then what waited moves over.
    storage.claim_if_new(blobs, "us", has_contents=False)
    assert blobs.reachable()
    assert blobs.move_incoming() == 1
    assert blobs.path(sha).is_relative_to(share)
    assert not any((incoming / "blobs").glob("*/*/*"))
    # Already there: what waits is just let go.
    waiting = incoming / blobs.path(sha).relative_to(share)
    waiting.parent.mkdir(parents=True, exist_ok=True)
    waiting.write_bytes(b"written offline")
    assert blobs.move_incoming() == 0
    assert not waiting.exists()
    storage.claim_if_new(blobs, "us", has_contents=True)  # marked already
    blobs.delete(sha)
    assert not blobs.exists(sha)


def test_only_a_new_folder_is_claimed(tmp_path: Path) -> None:
    # An unmounted share (an empty mount point) of a library with contents:
    # never claimed, nothing written into it.
    blobs = FilesystemStore(tmp_path / "share", tmp_path / "incoming")
    storage.claim_if_new(blobs, "us", has_contents=True)
    assert not blobs.reachable()
    # A folder from before markers, with contents: claimed as it is.
    old = FilesystemStore(tmp_path / "old")
    old.put([b"from before"], max_size=1 << 20)
    with_incoming = FilesystemStore(tmp_path / "old", tmp_path / "incoming2")
    storage.claim_if_new(with_incoming, "us", has_contents=True)
    assert with_incoming.reachable()
    # A folder that cannot be made (read-only above it): left alone.
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    try:
        unmade = FilesystemStore(locked / "share", tmp_path / "incoming3")
        storage.claim_if_new(unmade, "us", has_contents=False)
        assert not unmade.reachable()
    finally:
        locked.chmod(0o700)
    # Without an incoming folder nothing changes (as before).
    plain = FilesystemStore(tmp_path / "plain")
    storage.claim_if_new(plain, "us", has_contents=True)
    assert plain.reachable() and not (tmp_path / "plain" / storage.MARKER).exists()


def test_files_say_when_the_folder_is_away(
    client: TestClient, db: Session, tmp_path: Path
) -> None:
    blobs = FilesystemStore(tmp_path / "share", tmp_path / "incoming")
    app = client.app
    assert isinstance(app, FastAPI)
    app.state.blobs = blobs
    claim_storage(db, blobs)
    ada = Person(client, db, "ada")
    paper = ada.add("On the share")
    upload = ada.post(
        f"/api/items/{paper['id']}/files",
        files={"upload": ("p.pdf", PDF, "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]
    assert ada.get(f"/api/files/{file_id}/content").content == PDF
    # The share goes away (unmounted: its files and marker with it).
    for stored in (tmp_path / "share").rglob("*"):
        if stored.is_file():
            stored.unlink()
    away = ada.get(f"/api/files/{file_id}/content")
    assert away.status_code == 503
    assert "not reachable" in away.json()["detail"]
    # Back, with the marker but without that file: missing, not away.
    claim_storage(db, blobs)
    (tmp_path / "share" / storage.MARKER).write_text("us\n")
    assert ada.get(f"/api/files/{file_id}/content").status_code == 404
