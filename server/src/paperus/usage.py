"""How much storage paperus uses and how much is free (the sidebar,
Administration → Server stats, Prometheus)."""

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paperus.config import Settings
from paperus.models import Blob

# Walking the backup folder takes a while: its size is kept this long.
CACHE_SECONDS = 60
_folder_sizes: dict[Path, tuple[float, int]] = {}


@dataclass
class Disk:
    total: int
    used: int
    free: int


@dataclass
class Usage:
    library_bytes: int
    """The stored files (each content once)."""
    disk: Disk | None
    """The disk the files are on (None with S3: no fixed size)."""
    backups_bytes: int | None
    """The backups folder (None if there is none)."""
    backups_disk: Disk | None
    """The disk of the backups, if it is another one."""


def usage(db: Session, settings: Settings) -> Usage:
    library = int(db.scalar(select(func.coalesce(func.sum(Blob.size), 0))) or 0)
    disk = (
        _disk(settings.storage_path)
        if settings.storage_backend == "filesystem"
        else None
    )
    backups = settings.backup_path if settings.backup_path.is_dir() else None
    backups_disk = None
    if backups is not None and not _same_disk(backups, settings):
        backups_disk = _disk(backups)
    return Usage(
        library_bytes=library,
        disk=disk,
        backups_bytes=_folder_size(backups) if backups is not None else None,
        backups_disk=backups_disk,
    )


def _disk(path: Path) -> Disk | None:
    try:
        total, used, free = shutil.disk_usage(path)
    except OSError:
        return None
    return Disk(total=total, used=used, free=free)


def _same_disk(path: Path, settings: Settings) -> bool:
    if settings.storage_backend != "filesystem":
        return False
    try:
        return os.stat(path).st_dev == os.stat(settings.storage_path).st_dev
    except OSError:
        return False


def _folder_size(path: Path) -> int:
    now = time.monotonic()
    cached = _folder_sizes.get(path)
    if cached is not None and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    total = 0
    for folder, _, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(folder, name)).st_size
            except OSError:
                continue
    _folder_sizes[path] = (now, total)
    return total
