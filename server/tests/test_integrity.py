"""Integrity checks: missing, damaged and unused stored contents."""

import os
import time

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus import integrity
from paperus.storage import BlobStore, FilesystemStore
from tests.people import Person

PDF = b"%PDF-1.7\n" + b"x" * 3000 + b"\n%%EOF\n"
OTHER = b"%PDF-1.7\n" + b"y" * 3000 + b"\n%%EOF\n"


def test_check(client: TestClient, db: Session, blobs: BlobStore) -> None:
    assert isinstance(blobs, FilesystemStore)
    root = Person(client, db, "root", admin=True)
    good, gone, hurt = root.add("Good"), root.add("Gone"), root.add("Hurt")
    shas = {}
    for item, data in ((good, PDF), (gone, OTHER), (hurt, PDF + b"z")):
        file = root.post(
            f"/api/items/{item['id']}/files",
            files={"upload": ("p.pdf", data, "application/pdf")},
        ).json()
        shas[item["title"]] = bytes.fromhex(file["sha256"])
    blobs.delete(shas["Gone"])  # e.g. a restore without files
    blobs.path(shas["Hurt"]).write_bytes(b"changed on disk")
    # Contents nothing uses: an old one and a fresh one (maybe an upload).
    stray = blobs.put([b"left over"], max_size=100)
    fresh = blobs.put([b"just uploaded"], max_size=100)
    hour_ago = time.time() - 7200
    os.utime(blobs.path(stray.sha256), (hour_ago, hour_ago))

    quick = integrity.check(db, blobs)
    assert (quick.contents, quick.missing, quick.damaged) == (3, 1, 0)
    assert [p.title for p in quick.problems] == ["Gone"]
    assert (quick.unused, quick.unused_bytes) == (1, len(b"left over"))
    deep = integrity.check(db, blobs, deep=True)
    assert (deep.missing, deep.damaged) == (1, 1)
    assert sorted(p.title for p in deep.problems) == ["Gone", "Hurt"]

    cleaned = integrity.check(db, blobs, remove_unused=True)
    assert (cleaned.removed, cleaned.unused) == (1, 0)
    assert not blobs.exists(stray.sha256) and blobs.exists(fresh.sha256)
    # The last report, for the settings page.
    report = root.get("/api/admin/integrity").json()
    assert report["removed"] == 1 and report["missing"] == 1
    assert root.post("/api/admin/jobs/integrity-deep").status_code == 202
