"""A folder of stored files belongs to one library (``storage.owns``): two
sharing one would each delete what the other's database knows."""

import hashlib
import os
import time
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session

from paperus import integrity, storage, system, trash
from paperus.models import Blob
from paperus.storage import BlobStore, FilesystemStore, S3Store


def stored(blobs: BlobStore, content: bytes) -> bytes:
    """Content in the folder, as if from long ago (past the grace time)."""
    assert isinstance(blobs, FilesystemStore)
    sha = blobs.put([content], max_size=1 << 20).sha256
    path = blobs.path(sha)
    old = time.time() - 30 * 86400
    os.utime(path, (old, old))
    return sha


def test_only_the_owner_deletes(db: Session, blobs: BlobStore) -> None:
    assert isinstance(blobs, FilesystemStore)
    marker = blobs.root / storage.MARKER
    # Ours: claimed at the first clean-up, unused contents deleted.
    mine = stored(blobs, b"mine, no longer used")
    db.add(Blob(sha256=mine, size=20))
    db.commit()
    assert trash.collect_garbage(db, blobs) == (1, 20)
    assert marker.read_text().strip() == system.installation_id(db)
    assert not blobs.exists(mine)

    # Another library's folder: its rows go, its files stay.
    marker.write_text("another library\n")
    theirs = stored(blobs, b"another library's")
    db.add(Blob(sha256=theirs, size=17))
    db.commit()
    assert trash.collect_garbage(db, blobs) == (1, 17)
    assert db.get(Blob, theirs) is None
    assert blobs.exists(theirs)
    report = integrity.check(db, blobs, remove_unused=True)
    assert report.unused == 1
    assert blobs.exists(theirs)

    # Out of reach (an unmounted share): nothing deleted either.
    assert hashlib.sha256(b"another library's").digest() == theirs
    marker.unlink()
    blobs.root.chmod(0o500)
    try:
        assert not storage.owns(blobs, system.installation_id(db))
    finally:
        blobs.root.chmod(0o700)
    assert storage.owns(blobs, system.installation_id(db))


def test_other_stores_and_unreadable_markers(blobs: BlobStore, tmp_path: Path) -> None:
    # S3: a bucket is no folder another library shares by chance.
    unused_client = cast(Any, None)
    assert storage.owns(S3Store(unused_client, "bucket", "", tmp_path), "us")
    assert isinstance(blobs, FilesystemStore)
    (blobs.root / storage.MARKER).mkdir(parents=True)
    assert not storage.owns(blobs, "us")
