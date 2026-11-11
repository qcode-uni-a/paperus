"""Integrity checks (Administration → Settings → Integrity checks): whether
every file's stored contents exist (and, deeply, still match their
SHA-256), and which stored contents nothing uses any more."""

import hashlib
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import storage, system
from paperus.models import Blob, File, Item, SystemSetting, Version
from paperus.storage import BlobStore

KEY = "integrity"
# Contents written this recently may belong to an upload not saved yet.
GRACE = timedelta(hours=1)
# How many problems a report lists by name (the counts are always complete).
LISTED = 100


class Problem(BaseModel):
    file_id: str
    filename: str
    item_id: str
    title: str


class Report(BaseModel):
    checked_at: datetime
    deep: bool
    """The contents were read and their SHA-256 compared."""
    contents: int
    """Stored contents the library uses."""
    missing: int
    """Of those, missing from the storage."""
    damaged: int
    """Of those, changed (only checked deeply)."""
    problems: list[Problem]
    """Files with missing or damaged contents (the first ``LISTED``)."""
    unused: int
    """Stored contents nothing uses (older than an hour)."""
    unused_bytes: int
    removed: int = 0
    """Unused contents removed in this run."""


def check(
    db: Session, blobs: BlobStore, *, deep: bool = False, remove_unused: bool = False
) -> Report:
    """Compare the database with the storage; saves the report."""
    known = {sha: size for sha, size in db.execute(select(Blob.sha256, Blob.size))}
    stored = {sha: (written, size) for sha, written, size in blobs.iter_stored()}
    missing = [sha for sha in known if sha not in stored]
    damaged = (
        [sha for sha in known if sha in stored and not _matches(blobs, sha)]
        if deep
        else []
    )
    cutoff = datetime.now(UTC) - GRACE
    unused = [
        sha
        for sha, (written, _) in stored.items()
        if sha not in known and written < cutoff
    ]
    unused_bytes = sum(stored[sha][1] for sha in unused)
    removed = 0
    # Only from a folder this library owns (``storage.owns``).
    if remove_unused and unused and storage.owns(blobs, system.installation_id(db)):
        for sha in unused:
            blobs.delete(sha)
            removed += 1
    report = Report(
        checked_at=datetime.now(UTC),
        deep=deep,
        contents=len(known),
        missing=len(missing),
        damaged=len(damaged),
        problems=_problems(db, [*missing, *damaged]),
        unused=len(unused) - removed,
        unused_bytes=0 if removed else unused_bytes,
        removed=removed,
    )
    value = report.model_dump(mode="json")
    db.execute(
        insert(SystemSetting)
        .values(key=KEY, value=value)
        .on_conflict_do_update(index_elements=["key"], set_={"value": value})
    )
    db.commit()
    return report


def last_report(db: Session) -> Report | None:
    row = db.get(SystemSetting, KEY)
    return Report.model_validate(row.value) if row else None


def _matches(blobs: BlobStore, sha: bytes) -> bool:
    digest = hashlib.sha256()
    try:
        for chunk in blobs.iter_bytes(sha):
            digest.update(chunk)
    except OSError:
        return False
    return digest.digest() == sha


def _problems(db: Session, shas: list[bytes]) -> list[Problem]:
    if not shas:
        return []
    rows = db.execute(
        select(File.id, File.filename, Item.id, Item.title)
        .join(Version, Version.id == File.version_id)
        .join(Item, Item.id == Version.item_id)
        .where(File.blob_sha256.in_(shas))
        .order_by(Item.title)
        .limit(LISTED)
    ).all()
    return [
        Problem(file_id=str(f), filename=name, item_id=str(i), title=title)
        for f, name, i, title in rows
    ]
