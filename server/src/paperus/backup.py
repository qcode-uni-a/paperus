"""Backups of the database and, optionally, the files.

A backup is a folder in ``Settings.backup_path``, named by its time
(``2026-11-05T03-00-00Z``):

- ``manifest.json``: paperus version, database migration, time, whether it
  has files, and per table its row count and SHA-256;
- ``tables/<table>.tsv.gz``: each table as Postgres ``COPY`` text, all
  written from one consistent snapshot;
- ``blobs.txt.gz``: the files' SHA-256s, if files are included.

Files are content-addressed and never change, so all backups share one pool
(``files/ab/<sha256>``) and each copies only what is new. paperus writes and
reads the tables itself, so neither ``pg_dump`` nor the same Postgres version
is needed; restoring creates the schema at the backup's migration, loads the
data and migrates up to the running version. The job queue's tables are left
out: the worker's sweeps queue unfinished work again.
"""

import gzip
import hashlib
import json
import logging
import re
import shutil
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import psycopg
from alembic.script import ScriptDirectory
from psycopg import sql
from sqlalchemy import Engine, Table, text
from sqlalchemy.engine import Connection

from paperus import __version__
from paperus.config import Settings
from paperus.migrate import alembic_config, migrate
from paperus.models import Base
from paperus.storage import BlobStore, FilesystemStore, blob_name

log = logging.getLogger(__name__)

FORMAT = 1
PARTIAL = ".partial"


class BackupError(Exception):
    pass


@dataclass
class TableDump:
    rows: int
    sha256: str


@dataclass
class Manifest:
    name: str
    created_at: str
    paperus_version: str
    revision: str
    """The database migration the backup was taken at."""
    with_files: bool
    tables: dict[str, TableDump] = field(default_factory=dict)
    files: int = 0
    size: int = 0
    """Bytes of the backup's own folder (the shared file pool not counted)."""
    format: int = FORMAT

    @classmethod
    def read(cls, folder: Path) -> "Manifest":
        data = json.loads((folder / "manifest.json").read_text())
        data["name"] = folder.name  # the folder is what counts
        data["tables"] = {k: TableDump(**v) for k, v in data["tables"].items()}
        return cls(**data)

    def write(self, folder: Path) -> None:
        (folder / "manifest.json").write_text(json.dumps(asdict(self), indent=2))


def _tables() -> list[Table]:
    """Our tables in dependency order (the job queue's are not ours)."""
    return list(Base.metadata.sorted_tables)


def _columns(table: Table) -> list[str]:
    """Stored columns only: generated ones are computed again on load."""
    return [c.name for c in table.columns if c.computed is None]


def _head(connection: Connection) -> str:
    revision = connection.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar()
    if revision is None:
        raise BackupError("the database has no schema yet")
    return revision


def _folder_size(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def create_backup(
    engine: Engine, blobs: BlobStore, root: Path, *, with_files: bool
) -> Manifest:
    """Write a backup to ``root``; returns its manifest."""
    name = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    folder = root / (name + PARTIAL)
    (folder / "tables").mkdir(parents=True)
    try:
        with engine.connect() as connection:
            # One snapshot for every table.
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            manifest = Manifest(
                name=name,
                created_at=datetime.now(UTC).isoformat(),
                paperus_version=__version__,
                revision=_head(connection),
                with_files=with_files,
            )
            raw = _psycopg(connection)
            for table in _tables():
                manifest.tables[table.name] = _dump_table(
                    raw, table, folder / "tables" / f"{table.name}.tsv.gz"
                )
            shas: list[bytes] = []
            if with_files:
                shas = [
                    row[0]
                    for row in connection.execute(
                        text("SELECT sha256 FROM blobs ORDER BY sha256")
                    )
                ]
        if with_files:
            manifest.files = _copy_blobs_out(blobs, root / "files", shas)
            with gzip.open(folder / "blobs.txt.gz", "wt") as out:
                out.writelines(sha.hex() + "\n" for sha in shas)
        manifest.size = _folder_size(folder)
        manifest.write(folder)
        folder.rename(root / name)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    log.info(
        "backup %s written (%d tables, %d files)",
        name,
        len(manifest.tables),
        manifest.files,
    )
    return manifest


def _psycopg(connection: Connection) -> psycopg.Connection:
    raw = connection.connection.dbapi_connection
    if not isinstance(raw, psycopg.Connection):
        raise BackupError("backups need the psycopg database driver")
    return raw


def _copy(table: Table, direction: Literal["TO STDOUT", "FROM STDIN"]) -> sql.Composed:
    """``COPY "table" ("a", "b") TO STDOUT`` (or ``FROM STDIN``)."""
    return sql.SQL("COPY {} ({}) {}").format(
        sql.Identifier(table.name),
        sql.SQL(", ").join(sql.Identifier(c) for c in _columns(table)),
        sql.SQL(direction),
    )


def _dump_table(raw: psycopg.Connection, table: Table, target: Path) -> TableDump:
    digest = hashlib.sha256()
    rows = 0
    with (
        raw.cursor() as cursor,
        gzip.open(target, "wb", compresslevel=6) as out,
        cursor.copy(_copy(table, "TO STDOUT")) as copy,
    ):
        for chunk in copy:
            data = bytes(chunk)
            digest.update(data)
            rows += data.count(b"\n")
            out.write(data)
    return TableDump(rows=rows, sha256=digest.hexdigest())


def _copy_blobs_out(blobs: BlobStore, pool: Path, shas: list[bytes]) -> int:
    for sha in shas:
        target = pool / blob_name(sha)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(PARTIAL)
        with partial.open("wb") as out:
            for chunk in blobs.iter_bytes(sha):
                out.write(chunk)
        partial.replace(target)
    return len(shas)


def list_backups(root: Path) -> list[Manifest]:
    """Finished backups, newest first."""
    if not root.is_dir():
        return []
    found = []
    for folder in root.iterdir():
        if folder.is_dir() and (folder / "manifest.json").is_file():
            try:
                found.append(Manifest.read(folder))
            except (ValueError, TypeError, KeyError):
                log.warning("unreadable backup %s", folder.name)
    return sorted(found, key=lambda m: m.name, reverse=True)


def _blob_list(folder: Path) -> Iterator[str]:
    listing = folder / "blobs.txt.gz"
    if listing.is_file():
        with gzip.open(listing, "rt") as lines:
            yield from (line.strip() for line in lines if line.strip())


def delete_backup(root: Path, name: str) -> None:
    folder = root / name
    if "/" in name or name.startswith(".") or not (folder / "manifest.json").is_file():
        raise BackupError(f"no backup {name!r}")
    shutil.rmtree(folder)
    prune_pool(root)


def prune(root: Path, keep: int) -> list[str]:
    """Keep the newest ``keep`` backups; returns the names removed."""
    removed = [m.name for m in list_backups(root)[keep:]]
    for name in removed:
        shutil.rmtree(root / name)
    # Leftovers of interrupted backups.
    for folder in root.glob(f"*{PARTIAL}"):
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
    prune_pool(root)
    return removed


def prune_pool(root: Path) -> None:
    """Remove files no remaining backup needs."""
    pool = root / "files"
    if not pool.is_dir():
        return
    needed = {sha for m in list_backups(root) for sha in _blob_list(root / m.name)}
    for path in pool.rglob("*"):
        if path.is_file() and path.name not in needed:
            path.unlink()


def due(
    last: datetime | None,
    schedule: str,
    hour: int,
    now: datetime,
    *,
    weekday: int = 0,
) -> bool:
    """Whether a scheduled job should run now (checked every hour); weekly
    ones on ``weekday`` (Monday 0, as backups; Sunday 6)."""
    if schedule == "off" or now.hour != hour:
        return False
    if schedule == "weekly" and now.weekday() != weekday:
        return False
    return last is None or now - last > timedelta(hours=20)


def last_backup_time(root: Path) -> datetime | None:
    backups = list_backups(root)
    return datetime.fromisoformat(backups[0].created_at) if backups else None


# Checking before a restore


@dataclass
class RestoreCheck:
    """Where the backup's files would come from, before restoring it."""

    name: str
    with_files: bool
    """Whether the backup has its own copy of the files."""
    needed: int
    """Files the backup's papers use (not in the trash)."""
    in_storage: int
    """Of those, already in the file storage (identical: same SHA-256)."""
    from_backup: int
    """Of those, not in the storage but in the backup: copied back."""
    missing: int
    """Neither in the storage nor in the backup."""
    affected: list[str]
    """Titles of papers that would lack a file (at most 20)."""
    affected_count: int
    extra: int | None
    """Files in the storage the backup does not know (probably added after
    it; they stay); None when the storage cannot be listed (S3)."""


def _rows(folder: Path, table: str) -> Iterator[list[str | None]]:
    """The rows of a dumped table, as COPY text fields (None for NULL)."""
    path = folder / "tables" / f"{table}.tsv.gz"
    with gzip.open(path, "rt", encoding="utf-8") as lines:
        for line in lines:
            yield [_unescape(field) for field in line.rstrip("\n").split("\t")]


_ESCAPE = re.compile(r"\\(.)")
_ESCAPES = {"t": "\t", "n": "\n", "r": "\r", "b": "\b", "f": "\f", "v": "\v"}


def _unescape(field: str) -> str | None:
    """A field of Postgres COPY text format (backslash escapes, NULL as \\N)."""
    if field == "\\N":
        return None
    if "\\" not in field:
        return field
    return _ESCAPE.sub(lambda m: _ESCAPES.get(m[1], m[1]), field)


def _column(table: str, name: str) -> int:
    columns = _columns(Base.metadata.tables[table])
    return columns.index(name)


def check_restore(blobs: BlobStore, root: Path, name: str) -> RestoreCheck:
    folder = root / name
    if not (folder / "manifest.json").is_file():
        raise BackupError(f"no backup {name!r} in {root}")
    manifest = Manifest.read(folder)
    pool = root / "files"

    # Which items use which files (live ones only).
    version_item = {
        row[_column("versions", "id")]: row[_column("versions", "item_id")]
        for row in _rows(folder, "versions")
    }
    titles: dict[str | None, str | None] = {}
    trashed: set[str | None] = set()
    for row in _rows(folder, "items"):
        titles[row[_column("items", "id")]] = row[_column("items", "title")]
        if row[_column("items", "deleted_at")] is not None:
            trashed.add(row[_column("items", "id")])
    users: dict[bytes, set[str | None]] = {}
    for row in _rows(folder, "files"):
        if row[_column("files", "deleted_at")] is not None:
            continue
        item = version_item.get(row[_column("files", "version_id")])
        if item in trashed:
            continue
        sha = bytes.fromhex((row[_column("files", "blob_sha256")] or "")[2:])
        users.setdefault(sha, set()).add(item)

    in_storage = from_backup = missing = 0
    affected: set[str | None] = set()
    for sha, items in users.items():
        if blobs.exists(sha):
            in_storage += 1
        elif manifest.with_files and (pool / blob_name(sha)).is_file():
            from_backup += 1
        else:
            missing += 1
            affected |= items
    extra = None
    if isinstance(blobs, FilesystemStore):
        stored = blobs.root / "blobs"
        known = {sha.hex() for sha in users}
        extra = (
            sum(1 for p in stored.rglob("*") if p.is_file() and p.name not in known)
            if stored.is_dir()
            else 0
        )
    names = sorted(titles.get(item) or "Untitled" for item in affected)
    return RestoreCheck(
        name=name,
        with_files=manifest.with_files,
        needed=len(users),
        in_storage=in_storage,
        from_backup=from_backup,
        missing=missing,
        affected=names[:20],
        affected_count=len(names),
        extra=extra,
    )


# Restoring


def restore_backup(
    settings: Settings,
    engine: Engine,
    blobs: BlobStore,
    root: Path,
    name: str,
    *,
    replace: bool,
) -> Manifest:
    """Restore a backup into the database (and missing files into the store).

    The database must be empty, or ``replace`` must be given: then all its
    data is dropped first.
    """
    folder = root / name
    if not (folder / "manifest.json").is_file():
        raise BackupError(f"no backup {name!r} in {root}")
    manifest = Manifest.read(folder)
    if manifest.format != FORMAT:
        raise BackupError(f"backup format {manifest.format} is not supported")
    known = {
        s.revision
        for s in ScriptDirectory.from_config(alembic_config(settings)).walk_revisions()
    }
    if manifest.revision not in known:
        raise BackupError(
            f"the backup is from a newer paperus ({manifest.paperus_version}); "
            f"update paperus first, then restore"
        )
    _check_files(folder, manifest)

    with engine.begin() as connection:
        has_schema = connection.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar()
        if has_schema and not replace:
            users = connection.execute(text("SELECT count(*) FROM users")).scalar()
            if users:
                raise BackupError(
                    "the database is not empty; restore into an empty one or replace it"
                )
        if has_schema:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    migrate(settings, manifest.revision)

    with engine.begin() as connection:
        # Rows go in table by table; checks between tables wait until all are in.
        connection.execute(text("SET session_replication_role = replica"))
        raw = _psycopg(connection)
        tables = [t for t in _tables() if t.name in manifest.tables]
        # Empty them all at once first (migrations add a few rows), as
        # emptying one table also empties those pointing to it.
        names = ", ".join(f'"{t.name}"' for t in tables)
        connection.execute(text(f"TRUNCATE {names}"))
        for table in tables:
            _load_table(raw, table, folder / "tables" / f"{table.name}.tsv.gz")
        connection.execute(text("SET session_replication_role = DEFAULT"))
    migrate(settings)

    if manifest.with_files:
        _restore_blobs(blobs, root / "files", _blob_list(folder))
    log.info("backup %s restored", name)
    return manifest


def _check_files(folder: Path, manifest: Manifest) -> None:
    for table, dump in manifest.tables.items():
        digest = hashlib.sha256()
        with gzip.open(folder / "tables" / f"{table}.tsv.gz", "rb") as data:
            while chunk := data.read(1 << 20):
                digest.update(chunk)
        if digest.hexdigest() != dump.sha256:
            raise BackupError(f"the backup's table {table} is damaged")


def _load_table(raw: psycopg.Connection, table: Table, source: Path) -> None:
    with (
        raw.cursor() as cursor,
        gzip.open(source, "rb") as data,
        cursor.copy(_copy(table, "FROM STDIN")) as copy,
    ):
        while chunk := data.read(1 << 20):
            copy.write(chunk)


def _restore_blobs(blobs: BlobStore, pool: Path, shas: Iterator[str]) -> None:
    for hex_sha in shas:
        sha = bytes.fromhex(hex_sha)
        if blobs.exists(sha):
            continue
        source = pool / blob_name(sha)
        if not source.is_file():
            log.warning("file %s is missing from the backup", hex_sha)
            continue

        def chunks(path: Path = source) -> Iterator[bytes]:
            with path.open("rb") as stream:
                while chunk := stream.read(1 << 20):
                    yield chunk

        blobs.put(chunks(), max_size=1 << 62)
