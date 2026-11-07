"""Storage used and free: the files, the backups and their disks."""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from paperus import usage
from paperus.config import Settings


@pytest.fixture
def backups(settings: Settings) -> Path:
    folder = settings.backup_path / "2026-11-05T03-00-00Z"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_bytes(b"x" * 100)
    # A link to nowhere is left out.
    (folder / "gone").symlink_to(folder / "nothing")
    return folder


def test_backups_on_the_same_disk(
    db: Session, settings: Settings, backups: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(usage, "_folder_sizes", {})
    settings.storage_path.mkdir(parents=True)
    found = usage.usage(db, settings)
    assert found.library_bytes == 0
    assert found.disk is not None and found.disk.total >= found.disk.free > 0
    assert (found.backups_bytes, found.backups_disk) == (100, None)
    # Counted again only after a minute.
    (backups / "tables.tsv.gz").write_bytes(b"x" * 50)
    assert usage.usage(db, settings).backups_bytes == 100
    monkeypatch.setattr(usage, "CACHE_SECONDS", 0)
    assert usage.usage(db, settings).backups_bytes == 150


def test_backups_on_a_disk_of_their_own(
    db: Session, settings: Settings, backups: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(usage, "_folder_sizes", {})
    # With S3 the files have no disk; the backups do.
    s3 = settings.model_copy(update={"storage_backend": "s3"})
    found = usage.usage(db, s3)
    assert found.disk is None and found.backups_disk is not None
    # A storage folder that is not there (yet): no disk to tell.
    found = usage.usage(db, settings)
    assert found.disk is None and found.backups_disk is not None


def test_without_backups(db: Session, settings: Settings) -> None:
    found = usage.usage(db, settings)
    assert (found.backups_bytes, found.backups_disk) == (None, None)
