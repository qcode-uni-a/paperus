"""Importing a paperus export (``paperus.export``) back, in one or more
zips.

Part 1's ``library.sqlite`` says what the export holds and how many parts
it has; every part's ``part.json`` says which export and part it is. Before
anything is added the person sees the export's owners ("Me" and groups)
and chooses where each goes (``ImportChoices``), and which parts are
missing (their files are then reported missing, not an error).

Everything is kept: versions with their kinds, labels, identifiers and
metadata, manual edits, files with their roles (each checked against its
SHA-256), tags with their sources, the collection tree with smart rules,
notes and their links, favourites, archive marks, reference lists. New rows
keep their ids where unused here, so importing again finds them; papers
already here (same id, identifier or file) are found, not added twice.

The zips are untrusted: nothing is unpacked by its own name (the database
goes to a temporary file of ours), sizes are checked first, the database is
opened read-only, and every value is checked before use.
"""

import dataclasses
import json
import logging
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
import zlib
from collections.abc import Callable, Generator, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import library, notes, organize
from paperus.access import Access
from paperus.export import (
    DATABASE,
    FORMAT,
    FORMAT_VERSION,
    PART_FILE,
    TABLES,
    part_name,
)
from paperus.identifiers import Scheme
from paperus.importing.apply import Report, _reason, item_with_file
from paperus.importing.choices import Choices, GroupSuggestion
from paperus.models import (
    Blob,
    Collection,
    CollectionItem,
    CollectionNote,
    Favourite,
    File,
    FileRole,
    FileSource,
    Identifier,
    Item,
    ItemReference,
    ItemTag,
    MetadataSource,
    Note,
    NoteItem,
    PinnedCollection,
    Tag,
    TagColor,
    TagSource,
    User,
    Version,
    VersionKind,
)
from paperus.storage import BlobStore, TooLarge

log = logging.getLogger(__name__)

NAME = "paperus"
"""The import's format, as shown."""
MAX_DATABASE_BYTES = 8 * 1024**3
MAX_PART_FILE = 64 * 1024
CHUNK = 1024 * 1024


class NotAnExport(ValueError):
    """Shown to the person as it is."""


# What the person sees before choosing.


class ExportOwner(BaseModel):
    id: str
    """The owner's id in the export."""
    kind: str
    """``me`` or ``group``."""
    name: str
    """"Me", or the group's path in the export ("Uni/QCode Lab")."""
    role: str | None
    items: int
    notes: int
    can_create: bool = False
    """A group: whether the person may create it here (with the levels
    above it that are missing)."""
    suggestions: list[GroupSuggestion] = []
    """Groups here of the same or a similar name the person may add papers
    to: only offered, never chosen by itself."""


class MissingPart(BaseModel):
    part: int
    name: str
    """The zip's file name."""
    files: int
    """How many files it holds."""


class ImportChoices(BaseModel):
    """A paperus export waiting for the person's choice of owners."""

    export_id: str
    name: str
    parts: int
    exported_by: str
    exported_at: str
    server_url: str | None
    options: dict[str, Any]
    uploaded: list[int]
    """The parts uploaded (from 1)."""
    missing: list[MissingPart]
    refused: list[str]
    """Uploaded files left out: of another export, or no part of one."""
    owners: list[ExportOwner]
    mapping: Choices | None = None
    """What the person chose (once the import starts)."""

    @field_validator("mapping", mode="before")
    @classmethod
    def _older(cls, value: object) -> object:
        """Imports started before the choices grew: owner id → library."""
        if isinstance(value, dict) and value and "owners" not in value:
            return {
                "owners": {
                    key: {"action": "into", "library_id": target}
                    for key, target in value.items()
                }
            }
        return value


@dataclass
class Plan:
    """What the import does with the export's owners, tags and collections
    (``paperus.importing.mapping.prepare``)."""

    owners: dict[str, uuid.UUID]
    """Owner id in the export → library here."""
    holding: dict[str, uuid.UUID] = field(default_factory=dict)
    """Owner id → the holding collection its papers and collections go into."""
    tags: dict[str, tuple[str, uuid.UUID | str | None]] = field(default_factory=dict)
    """Tag id → ("merge" or "map", the tag here) or ("new", its name)."""
    collections: dict[str, tuple[str, uuid.UUID | str | None]] = field(
        default_factory=dict
    )
    """Collection id → as for tags."""


@dataclass
class Upload:
    path: Path
    filename: str


@dataclass
class Marker:
    """A part's ``part.json``."""

    upload: Upload
    export_id: str
    name: str
    part: int
    parts: int


def read_marker(upload: Upload) -> Marker | None:
    """The part an upload is, None if it is no part of a paperus export."""
    if not zipfile.is_zipfile(upload.path):
        return None
    with zipfile.ZipFile(upload.path) as archive:
        found = [
            info
            for info in archive.infolist()
            if PurePosixPath(info.filename).name == PART_FILE
            and info.filename.count("/") == 1
        ]
        if not found or found[0].file_size > MAX_PART_FILE:
            return None
        try:
            data = json.loads(archive.read(found[0]))
        except (ValueError, zipfile.BadZipFile, zlib.error, EOFError):
            return None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return None
    if data.get("contents", "paperus") != "paperus":
        return None  # for another program: imported as its file is
    version = data.get("format_version")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise NotAnExport(
            f"{upload.filename} is from a newer paperus (export format {version}): "
            "update paperus here first."
        )
    try:
        marker = Marker(
            upload,
            str(uuid.UUID(str(data["export"]))),
            _safe_folder(data["name"]),
            int(data["part"]),
            int(data["parts"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if not 1 <= marker.part <= marker.parts:
        return None
    return marker


def _safe_folder(value: object) -> str:
    """The export's top folder: one plain name."""
    name = str(value)
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError(name)
    return name


@dataclass
class Opened:
    """An export's uploaded parts, its database open."""

    choices: ImportChoices
    database: sqlite3.Connection
    zips: dict[int, zipfile.ZipFile]
    name: str


def is_export(uploads: list[Upload]) -> bool:
    """Whether any upload is a part of a paperus export."""
    return any(read_marker(upload) is not None for upload in uploads)


@contextmanager
def opened(uploads: list[Upload], work: Path) -> Generator[Opened]:
    """Part 1's database and the parts of the same export; the others are
    refused. ``NotAnExport`` without part 1, or for two exports' first
    parts."""
    markers: list[Marker] = []
    refused: list[str] = []
    for upload in uploads:
        marker = read_marker(upload)
        if marker is None:
            refused.append(upload.filename)
        else:
            markers.append(marker)
    firsts = {m.export_id: m for m in markers if m.part == 1}
    if not firsts:
        if not markers:
            raise NotAnExport("This is no part of a paperus export.")
        example = markers[0]
        raise NotAnExport(
            "Part 1 holds the database: add it "
            f"({part_name(example.name, 1, example.parts)})."
        )
    if len(firsts) > 1:
        raise NotAnExport(
            "These are the first parts of different exports: import one at a time."
        )
    first = next(iter(firsts.values()))
    uploaded: dict[int, Upload] = {}
    for marker in markers:
        if marker.export_id != first.export_id or marker.parts != first.parts:
            refused.append(marker.upload.filename)
        else:
            uploaded.setdefault(marker.part, marker.upload)
    with ExitStack() as stack:
        folder = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=work)))
        database = _open_database(first, folder / DATABASE)
        stack.callback(database.close)
        meta = _meta(database, first)
        zips = {
            part: stack.enter_context(zipfile.ZipFile(upload.path))
            for part, upload in sorted(uploaded.items())
        }
        per_part = {
            row[0]: row[1]
            for row in _query(
                database,
                "SELECT part, count(*) FROM files WHERE included = 1 "
                "AND part IS NOT NULL GROUP BY part",
            )
        }
        choices = ImportChoices(
            export_id=first.export_id,
            name=first.name,
            parts=first.parts,
            exported_by=str(meta["exported_by"]),
            exported_at=str(meta["exported_at"]),
            server_url=meta["server_url"],
            options=meta["options"],
            uploaded=sorted(uploaded),
            missing=[
                MissingPart(
                    part=n,
                    name=part_name(first.name, n, first.parts),
                    files=int(per_part.get(n, 0)),
                )
                for n in range(1, first.parts + 1)
                if n not in uploaded
            ],
            refused=refused,
            owners=_owners(database),
        )
        yield Opened(choices, database, zips, first.name)


def _open_database(first: Marker, target: Path) -> sqlite3.Connection:
    """Part 1's database, copied out of the zip under our own name and
    opened read-only."""
    member = f"{first.name}/{DATABASE}"
    try:
        with zipfile.ZipFile(first.upload.path) as archive:
            info = archive.getinfo(member)
            if info.file_size > MAX_DATABASE_BYTES:
                raise NotAnExport(
                    f"The database is {info.file_size // 2**20} MB; at most "
                    f"{MAX_DATABASE_BYTES // 2**30} GB can be read."
                )
            with archive.open(info) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out, CHUNK)
    except KeyError as error:
        raise NotAnExport(f"{first.upload.filename} has no {DATABASE}.") from error
    except (zipfile.BadZipFile, zlib.error, EOFError) as error:
        raise NotAnExport(f"{DATABASE} could not be unpacked: {error}") from error
    database = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        database.execute("PRAGMA trusted_schema = OFF")
        tables = {
            row[0]
            for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    except sqlite3.DatabaseError as error:
        database.close()
        raise NotAnExport(f"{DATABASE} is not a SQLite database.") from error
    lacking = [table for table in TABLES if table not in tables]
    if lacking:
        database.close()
        raise NotAnExport(
            f"{DATABASE} has no table {lacking[0]}: not a paperus export."
        )
    database.row_factory = sqlite3.Row
    return database


def _query(
    database: sqlite3.Connection, sql: str, parameters: tuple[object, ...] = ()
) -> Iterator[sqlite3.Row]:
    try:
        yield from database.execute(sql, parameters)
    except sqlite3.Error as error:
        raise NotAnExport(f"{DATABASE} could not be read: {error}") from error


def _meta(database: sqlite3.Connection, first: Marker) -> dict[str, Any]:
    rows = list(_query(database, "SELECT * FROM paperus"))
    if len(rows) != 1:
        raise NotAnExport(f"{DATABASE} does not say what it is (table paperus).")
    row = dict(rows[0])
    version = row.get("format_version")
    if row.get("format") != FORMAT or not isinstance(version, int):
        raise NotAnExport(f"{DATABASE} is not a paperus export.")
    if version > FORMAT_VERSION:
        raise NotAnExport(
            f"This export is from a newer paperus (export format {version}): "
            "update paperus here first."
        )
    if row.get("export_id") != first.export_id:
        raise NotAnExport("Part 1's database belongs to another export.")
    try:
        options = json.loads(row.get("options") or "{}")
    except ValueError:
        options = {}
    row["options"] = options if isinstance(options, dict) else {}
    server = row.get("server_url")
    row["server_url"] = str(server) if server else None
    return row


def _owners(database: sqlite3.Connection) -> list[ExportOwner]:
    owners = []
    for row in _query(
        database,
        "SELECT id, kind, name, role,"
        " (SELECT count(*) FROM items WHERE library_id = owners.id),"
        " (SELECT count(*) FROM notes WHERE library_id = owners.id)"
        " FROM owners ORDER BY kind DESC, name",
    ):
        owners.append(
            ExportOwner(
                id=str(row[0]),
                kind="me" if row[1] == "me" else "group",
                name=str(row[2])[:500],
                role=str(row[3]) if row[3] else None,
                items=int(row[4]),
                notes=int(row[5]),
            )
        )
    return owners


# Checking values from the export.


def _uuid(value: object) -> uuid.UUID:
    return uuid.UUID(str(value))


def _time(value: object) -> datetime:
    moment = datetime.fromisoformat(str(value))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _optional_time(value: object) -> datetime | None:
    return None if value is None else _time(value)


def _text(value: object, length: int | None = None) -> str:
    if not isinstance(value, str):
        raise ValueError(f"not text: {value!r}")
    text = value.replace("\x00", "")
    return text if length is None else text[:length]


def _optional_text(value: object, length: int | None = None) -> str | None:
    return None if value is None else _text(value, length)


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _object(value: object) -> dict[str, Any]:
    parsed = json.loads(_text(value))
    if not isinstance(parsed, dict):
        raise ValueError("not a JSON object")
    return parsed


def _choice[E: StrEnum](value: object, kind: type[E], default: E) -> E:
    try:
        return kind(str(value))
    except ValueError:
        return default


# Adding it.


@dataclass
class _Run:
    db: Session
    blobs: BlobStore
    access: Access
    opened: Opened
    plan: Plan
    max_file_bytes: int
    report: Report
    file_added: Callable[[uuid.UUID], None]
    users: dict[str, uuid.UUID] = field(default_factory=dict)
    tags: dict[str, Tag] = field(default_factory=dict)
    collections: dict[str, uuid.UUID] = field(default_factory=dict)
    items: dict[str, uuid.UUID] = field(default_factory=dict)
    seen: dict[tuple[str, str], uuid.UUID] = field(default_factory=dict)
    new_files: list[uuid.UUID] = field(default_factory=list)

    @property
    def me(self) -> uuid.UUID:
        return self.access.user.id

    def rows(self, sql: str, *parameters: object) -> Iterator[sqlite3.Row]:
        return _query(self.opened.database, sql, parameters)

    def user(self, value: object) -> uuid.UUID | None:
        """The same person here (same id and username), else the importer."""
        if value is None:
            return None
        return self.users.get(str(value), self.me)

    def owner(self, value: object) -> uuid.UUID:
        return self.plan.owners[str(value)]

    def holding(self, value: object) -> Collection | None:
        """The holding collection of the owner's things, if it has one."""
        collection_id = self.plan.holding.get(str(value))
        return self.db.get(Collection, collection_id) if collection_id else None


def keep_id(db: Session, model: type[Any], value: object) -> dict[str, uuid.UUID]:
    """``{"id": …}`` with the export's id if unused here, else nothing (a
    new one is made)."""
    try:
        wanted = _uuid(value)
    except ValueError:
        return {}
    return {} if db.get(model, wanted) is not None else {"id": wanted}


def apply_export(
    db: Session,
    blobs: BlobStore,
    access: Access,
    opened: Opened,
    *,
    plan: Plan,
    max_file_bytes: int,
    progress: Callable[[int, int], None] = lambda done, total: None,
    file_added: Callable[[uuid.UUID], None] = lambda file_id: None,
) -> Report:
    """Add the export for the person as ``plan`` says (each owner's things
    to a library they may add to). Commits after each paper and note."""
    for target in set(plan.owners.values()):
        access.require_write(target)
    total_items = next(iter(_query(opened.database, "SELECT count(*) FROM items")))[0]
    run = _Run(
        db,
        blobs,
        access,
        opened,
        plan,
        max_file_bytes,
        Report(papers=total_items),
        file_added,
    )
    for missing in opened.choices.missing:
        run.report.problems.append(
            f"Part {missing.part} of {opened.choices.parts} was not uploaded "
            f"({missing.name}): its {missing.files} files are missing."
        )
    exported = {
        str(row[0]): str(row[1]) for row in run.rows("SELECT id, username FROM users")
    }
    for user_id, username in db.execute(
        select(User.id, User.username).where(
            User.id.in_([u for v in exported if (u := _maybe_uuid(v))])
        )
    ):
        if exported.get(str(user_id)) == username:
            run.users[str(user_id)] = user_id
    for row in run.rows("SELECT * FROM tags ORDER BY created_at, id"):
        _guarded(run, f"tag {row['name']}", lambda row=row: _tag(run, row))
    for row in _parents_first(list(run.rows("SELECT * FROM collections"))):
        _guarded(
            run, f"collection {row['name']}", lambda row=row: _collection(run, row)
        )
    total = total_items + next(iter(run.rows("SELECT count(*) FROM notes")))[0]
    done = 0
    for row in run.rows("SELECT * FROM items ORDER BY created_at, id"):
        _guarded(run, str(row["title"])[:100], lambda row=row: _item(run, row))
        for file_id in run.new_files:
            file_added(file_id)
        run.new_files.clear()
        done += 1
        progress(done, total)
    for row in run.rows("SELECT * FROM notes ORDER BY created_at, id"):
        name = notes.title_of(str(row["text"] or "")) or "a note"
        _guarded(run, name, lambda row=row: _note(run, row))
        done += 1
        progress(done, total)
    _guarded(run, "pinned collections", lambda: _pins(run))
    return run.report


def _guarded(run: _Run, name: str, step: Callable[[], None]) -> None:
    """One step in its own transaction: if it fails, what it did is undone
    (also in the counts and what it remembered) and the import goes on."""
    counts = dataclasses.replace(run.report, missing_files=[], problems=[])
    remembered = dict(run.seen), dict(run.items)
    missing, problems = len(run.report.missing_files), len(run.report.problems)
    try:
        step()
        run.db.commit()
    except Exception as error:
        run.db.rollback()
        log.warning("import of %s failed", name, exc_info=True)
        for counter in ("added", "found", "files", "notes", "collections"):
            setattr(run.report, counter, getattr(counts, counter))
        del run.report.missing_files[missing:]
        del run.report.problems[problems:]
        run.seen, run.items = remembered
        run.new_files.clear()
        run.report.problems.append(f"{name}: {_reason(error)}")


def _maybe_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _parents_first(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    by_parent: dict[str | None, list[sqlite3.Row]] = {}
    ids = {str(row["id"]) for row in rows}
    for row in rows:
        parent = str(row["parent_id"]) if row["parent_id"] is not None else None
        by_parent.setdefault(parent if parent in ids else None, []).append(row)
    ordered: list[sqlite3.Row] = []
    waiting: list[str | None] = [None]
    while waiting:
        for row in by_parent.pop(waiting.pop(0), []):
            ordered.append(row)
            waiting.append(str(row["id"]))
    return ordered


def _tag(run: _Run, row: sqlite3.Row) -> None:
    db, target = run.db, run.owner(row["library_id"])
    name = organize.clean_name(_text(row["name"]))[:100]
    # The same tag if the person sees it (imported before), wherever it is.
    tag = db.get(Tag, _uuid(row["id"]))
    if tag is None or not run.access.can_read(tag.library_id):
        decided, value = run.plan.tags.get(str(row["id"]), ("", None))
        if decided in ("merge", "map"):
            tag = db.get(Tag, value)
        elif decided == "new":
            name, tag = str(value)[:100], None
        else:
            tag = organize.find_tag(db, target, name)
    if tag is None:
        color = _choice(row["color"], TagColor, TagColor.GRAY) if row["color"] else None
        tag = Tag(
            **keep_id(db, Tag, row["id"]),
            created_at=_time(row["created_at"]),
            library_id=target,
            name=name,
            color=color,
            description=_optional_text(row["description"]),
            change=0,
        )
        db.add(tag)
        db.flush()
    run.tags[str(row["id"])] = tag


def _collection(run: _Run, row: sqlite3.Row) -> None:
    db, target = run.db, run.owner(row["library_id"])
    name = organize.clean_name(_text(row["name"]))[:200]
    parent_id = run.collections.get(str(row["parent_id"]))
    parent = db.get(Collection, parent_id) if parent_id else None
    if parent is not None and (parent.library_id != target or parent.rules is not None):
        parent = None
    if parent is None:
        # A group's collections in its holding collection (if it has one).
        parent = run.holding(row["library_id"])
    found = db.get(Collection, _uuid(row["id"]))
    decided, value = run.plan.collections.get(str(row["id"]), ("", None))
    if found is not None and run.access.can_read(found.library_id):
        pass  # imported before
    elif decided in ("merge", "map"):
        found = db.get(Collection, value)
    elif decided == "new":
        found, name = None, str(value)[:200]
    else:
        place = (
            Collection.parent_id == parent.id
            if parent
            else Collection.parent_id.is_(None)
        )
        found = db.scalar(
            select(Collection)
            .where(Collection.library_id == target, place, Collection.name == name)
            .limit(1)
        )
    if found is None:
        found = Collection(
            **keep_id(db, Collection, row["id"]),
            created_at=_time(row["created_at"]),
            library_id=target,
            name=name,
            description=_optional_text(row["description"]),
            parent_id=parent.id if parent else None,
            rules=_rules(run, row["rules"]),
            created_by=run.user(row["created_by"]),
            change=0,
        )
        db.add(found)
        db.flush()
        run.report.collections += 1
    run.collections[str(row["id"])] = found.id


def _rules(run: _Run, value: object) -> dict[str, Any] | None:
    """A smart collection's rules, its tags and owners those here."""
    if value is None:
        return None
    try:
        rules = organize.Rules.model_validate(_object(value))
    except (ValueError, ValidationError):
        return {}  # smart, matching everything: the rules could not be read
    tags = {key: tag.id for key, tag in run.tags.items()}
    for name in ("tags_all", "tags_any", "tags_none"):
        setattr(
            rules,
            name,
            [tags[str(t)] for t in getattr(rules, name) if str(t) in tags],
        )
    rules.owners = list(
        dict.fromkeys(
            run.plan.owners[str(o)] for o in rules.owners if str(o) in run.plan.owners
        )
    )
    return rules.model_dump(mode="json")


def _identifiers(
    run: _Run, version_id: object
) -> list[tuple[Scheme, str, sqlite3.Row]]:
    found = []
    for row in run.rows(
        "SELECT * FROM identifiers WHERE version_id = ? ORDER BY id", version_id
    ):
        try:
            found.append((Scheme(str(row["scheme"])), _text(row["value"], 2000), row))
        except ValueError:
            continue
    return found


def _existing(
    run: _Run, row: sqlite3.Row, keys: list[tuple[str, str]], shas: list[bytes]
) -> Item | None:
    """The paper if the person sees it already: this import's, the same
    id, the same identifier, or a file of the same content."""
    db, access = run.db, run.access
    for key in keys:
        if key in run.seen:
            return db.get(Item, run.seen[key])
    same = db.get(Item, _uuid(row["id"]))
    if same is not None and access.can_read_item(same):
        return same
    identifiers = [(Scheme(scheme), value) for scheme, value in keys]
    known = library.find_identifier(db, access.readable, identifiers)
    if known is not None:
        return known.version.item
    for sha in shas:
        item = item_with_file(db, access.readable, sha)
        if item is not None:
            return item
    return None


def _item(run: _Run, row: sqlite3.Row) -> None:
    db, access = run.db, run.access
    versions = list(
        run.rows("SELECT * FROM versions WHERE item_id = ? ORDER BY id", row["id"])
    )
    identifiers = {str(v["id"]): _identifiers(run, v["id"]) for v in versions}
    keys = list(
        dict.fromkeys(
            (scheme.value, value)
            for found in identifiers.values()
            for scheme, value, _ in found
        )
    )
    file_rows = list(
        run.rows(
            "SELECT files.* FROM files JOIN versions ON versions.id = files.version_id"
            " WHERE versions.item_id = ? ORDER BY files.id",
            row["id"],
        )
    )
    shas = [bytes.fromhex(_text(f["sha256"])) for f in file_rows]
    item = _existing(run, row, keys, shas)
    new = item is None
    if item is None:
        item = Item(
            **keep_id(db, Item, row["id"]),
            created_at=_time(row["created_at"]),
            library_id=run.owner(row["library_id"]),
            type=_text(row["type"], 64),
            title=_text(row["title"]),
            year=_int(row["year"]),
            file_wanted=bool(row["file_wanted"]),
            archived_at=_optional_time(row["archived_at"]),
            overrides=_object(row["overrides"]),
            added_by=run.user(row["added_by"]),
            deleted_at=_optional_time(row["deleted_at"]),
            deleted_by=run.user(row["deleted_by"]),
            change=0,
        )
        db.add(item)
        run.report.added += 1
    else:
        run.report.found += 1
    writable = new or access.can_write_item(item)
    version_map = _versions(
        run, item, versions, identifiers, writable=writable, new=new
    )
    if new:
        db.flush()
        library.refresh_item(item)
    for key in keys:
        run.seen[key] = item.id
    for sha in shas:
        run.seen[("file", sha.hex())] = item.id
    run.items[str(row["id"])] = item.id
    if writable:
        _files(run, item, file_rows, version_map)
    _item_tags(run, item, row["id"])
    _item_collections(run, item, row["id"])
    holding = run.holding(row["library_id"])
    if (
        holding is not None
        and item.library_id == holding.library_id
        and not any(c.collection_id == holding.id for c in item.collection_links)
    ):
        # A group's papers kept in the person's library, in its collection.
        item.collection_links.append(
            CollectionItem(collection_id=holding.id, added_by=run.me)
        )
    for star in run.rows("SELECT * FROM favourites WHERE item_id = ?", row["id"]):
        if run.db.get(Favourite, (run.me, item.id)) is None:
            item.favourites.append(
                Favourite(user_id=run.me, created_at=_time(star["created_at"]))
            )
    if writable:
        _references(run, item, row)


def _versions(
    run: _Run,
    item: Item,
    rows: list[sqlite3.Row],
    identifiers: dict[str, list[tuple[Scheme, str, sqlite3.Row]]],
    *,
    writable: bool,
    new: bool,
) -> dict[str, Version]:
    """The paper's versions here for those of the export: the same (by id
    or identifier), or added if the person may (the one shown changes only
    for a new paper)."""
    db = run.db
    found: dict[str, Version] = {}
    pinned = not new
    for row in rows:
        version = db.get(Version, _uuid(row["id"]))
        here = {(i.scheme, i.value): v for v in item.versions for i in v.identifiers}
        mine = [(s, v) for s, v, _ in identifiers[str(row["id"])]]
        if version is None or version.item_id != item.id:
            version = next((here[k] for k in mine if k in here), None)
        if version is None and writable:
            # Identifiers are unique per owner: one another paper has stays there.
            fresh = [
                found
                for found in identifiers[str(row["id"])]
                if library.find_identifier(db, [item.library_id], [found[:2]]) is None
            ]
            version = Version(
                **keep_id(db, Version, row["id"]),
                created_at=_time(row["created_at"]),
                kind=_choice(row["kind"], VersionKind, VersionKind.OTHER),
                label=_optional_text(row["label"]),
                csl=_object(row["csl"]),
                metadata_source=_choice(
                    row["metadata_source"], MetadataSource, MetadataSource.IMPORT
                ),
                pinned=bool(row["pinned"]) and not pinned,
                created_by=run.user(row["created_by"]),
                identifiers=_new_identifiers(run, fresh),
            )
            pinned = pinned or version.pinned
            item.versions.append(version)
            db.flush()
        if version is not None:
            found[str(row["id"])] = version
    return found


def _new_identifiers(
    run: _Run, rows: list[tuple[Scheme, str, sqlite3.Row]]
) -> list[Identifier]:
    seen: set[tuple[str, str]] = set()
    made = []
    for scheme, value, row in rows:
        if (scheme.value, value) in seen:
            continue
        seen.add((scheme.value, value))
        made.append(
            Identifier(
                **keep_id(run.db, Identifier, row["id"]),
                created_at=_time(row["created_at"]),
                scheme=scheme,
                value=value,
            )
        )
    return made


def _files(
    run: _Run, item: Item, rows: list[sqlite3.Row], versions: dict[str, Version]
) -> None:
    present = {f.blob_sha256 for v in item.versions for f in v.files}
    for row in rows:
        sha = bytes.fromhex(_text(row["sha256"]))
        if sha in present:
            continue
        version = versions.get(str(row["version_id"])) or library.preferred_version(
            item
        )
        if version is None:
            continue
        label = _optional_text(row["path"]) or _text(row["filename"])
        stored = _store(run, row, sha, label)
        if stored is None:
            continue
        file = File(
            **keep_id(run.db, File, row["id"]),
            created_at=_time(row["created_at"]),
            version=version,
            blob_sha256=sha,
            role=_choice(row["role"], FileRole, FileRole.OTHER),
            filename=_text(row["filename"], 255) or "file",
            media_type=_text(row["media_type"], 255),
            source=_choice(row["source"], FileSource, FileSource.IMPORT),
            uploaded_by=run.user(row["uploaded_by"]),
            deleted_at=_optional_time(row["deleted_at"]),
            deleted_by=run.user(row["deleted_by"]),
        )
        run.db.add(file)
        run.db.flush()
        present.add(sha)
        run.new_files.append(file.id)
        run.report.files += 1


def _store(run: _Run, row: sqlite3.Row, sha: bytes, label: str) -> bytes | None:
    """The file's content in the store (read from its part unless stored
    already), checked against its SHA-256; None if missing or damaged."""
    db, blobs = run.db, run.blobs
    # Taken from the store only if the person sees a file of it already: a
    # SHA-256 alone gives no one a file.
    if item_with_file(db, run.access.readable, sha, trash=True) is not None:
        return sha
    archive = run.opened.zips.get(_int(row["part"]) or 0)
    path = _optional_text(row["path"])
    if not row["included"] or path is None or archive is None:
        run.report.missing_files.append(label)
        return None
    member = f"{run.opened.name}/{path}"
    try:
        info = archive.getinfo(member)
    except KeyError:
        run.report.missing_files.append(label)
        return None
    try:
        with archive.open(info) as stream:
            stored = blobs.put(_chunks(stream), max_size=run.max_file_bytes)
    except TooLarge:
        run.report.problems.append(f"{label}: too large")
        return None
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError) as error:
        run.report.problems.append(f"{label}: damaged in the zip ({error}); left out")
        return None
    if stored.sha256 != sha:
        if db.get(Blob, stored.sha256) is None:
            blobs.delete(stored.sha256)
        run.report.problems.append(
            f"{label}: damaged (not the content the export lists); left out"
        )
        return None
    db.execute(
        insert(Blob).values(sha256=sha, size=stored.size).on_conflict_do_nothing()
    )
    return sha


def _chunks(stream: Any) -> Iterator[bytes]:  # noqa: ANN401 (a zip member)
    while chunk := stream.read(CHUNK):
        yield chunk


def _item_tags(run: _Run, item: Item, item_id: object) -> None:
    for link in run.rows("SELECT * FROM item_tags WHERE item_id = ?", item_id):
        tag = run.tags.get(str(link["tag_id"]))
        if tag is None or not run.access.may_tag(tag.library_id, item):
            continue
        if any(existing.tag_id == tag.id for existing in item.tag_links):
            continue
        item.tag_links.append(
            ItemTag(
                tag_id=tag.id,
                tag=tag,
                source=_choice(link["source"], TagSource, TagSource.MANUAL),
                added_by=run.user(link["added_by"]),
                created_at=_time(link["created_at"]),
            )
        )


def _item_collections(run: _Run, item: Item, item_id: object) -> None:
    access = run.access
    for link in run.rows("SELECT * FROM collection_items WHERE item_id = ?", item_id):
        collection_id = run.collections.get(str(link["collection_id"]))
        collection = run.db.get(Collection, collection_id) if collection_id else None
        if (
            collection is None
            or collection.rules is not None
            or not access.can_write(collection.library_id)
            or not access.may_hold(collection.library_id, item)
            or any(c.collection_id == collection.id for c in item.collection_links)
        ):
            continue
        item.collection_links.append(
            CollectionItem(
                collection_id=collection.id,
                added_by=run.user(link["added_by"]),
                created_at=_time(link["created_at"]),
            )
        )


def _references(run: _Run, item: Item, row: sqlite3.Row) -> None:
    """The reference list, if the paper has none here yet."""
    has = run.db.scalar(
        select(ItemReference.position).where(ItemReference.item_id == item.id).limit(1)
    )
    if has is not None:
        return
    references = [
        ItemReference(
            item_id=item.id,
            position=position,
            text=_text(ref["text"]),
            title=_optional_text(ref["title"]),
            authors=_optional_text(ref["authors"]),
            year=_int(ref["year"]),
            container=_optional_text(ref["container"]),
            doi=_optional_text(ref["doi"]),
            arxiv=_optional_text(ref["arxiv"]),
            url=_optional_text(ref["url"]),
        )
        for position, ref in enumerate(
            run.rows(
                "SELECT * FROM item_references WHERE item_id = ? ORDER BY position",
                row["id"],
            ),
            1,
        )
    ]
    if not references:
        return
    run.db.add_all(references)
    item.references_source = _optional_text(row["references_source"], 16)
    item.references_checked_at = datetime.now(UTC)


def _note(run: _Run, row: sqlite3.Row) -> None:
    db, access = run.db, run.access
    target = run.owner(row["library_id"])
    text = _text(row["text"])
    note = db.get(Note, _uuid(row["id"]))
    if note is None or not access.can_read(note.library_id):
        note = db.scalar(
            select(Note)
            .where(
                Note.library_id == target,
                Note.text == text,
                Note.deleted_at.is_(None),
            )
            .limit(1)
        )
    if note is None:
        note = Note(
            **keep_id(db, Note, row["id"]),
            created_at=_time(row["created_at"]),
            library_id=target,
            text=text,
            title=notes.title_of(text),
            created_by=run.user(row["created_by"]),
            changed_by=run.user(row["changed_by"]),
            changed_at=_time(row["changed_at"]),
            text_changed_at=_time(row["text_changed_at"]),
            deleted_at=_optional_time(row["deleted_at"]),
            deleted_by=run.user(row["deleted_by"]),
            change=0,
        )
        db.add(note)
        db.flush()
        notes.index(db, note)
        run.report.notes += 1
    if access.can_write(note.library_id):
        for link in run.rows("SELECT * FROM note_items WHERE note_id = ?", row["id"]):
            item_id = run.items.get(str(link["item_id"]))
            if item_id is None or any(i.item_id == item_id for i in note.item_links):
                continue
            page = _int(link["page"])
            note.item_links.append(
                NoteItem(
                    item_id=item_id,
                    page=page if page and page >= 1 else None,
                    added_by=run.user(link["added_by"]),
                    created_at=_time(link["created_at"]),
                )
            )
    holding = run.holding(row["library_id"])
    if (
        holding is not None
        and note.library_id == holding.library_id
        and not any(c.collection_id == holding.id for c in note.collection_links)
    ):
        note.collection_links.append(
            CollectionNote(collection_id=holding.id, added_by=run.me)
        )
    for link in run.rows("SELECT * FROM collection_notes WHERE note_id = ?", row["id"]):
        collection_id = run.collections.get(str(link["collection_id"]))
        collection = db.get(Collection, collection_id) if collection_id else None
        if (
            collection is None
            or collection.rules is not None
            or not access.can_write(collection.library_id)
            or not access.may_hold(collection.library_id, note)
            or any(c.collection_id == collection.id for c in note.collection_links)
        ):
            continue
        note.collection_links.append(
            CollectionNote(
                collection_id=collection.id,
                added_by=run.user(link["added_by"]),
                created_at=_time(link["created_at"]),
            )
        )


def _pins(run: _Run) -> None:
    pinned = set(
        run.db.scalars(
            select(PinnedCollection.collection_id).where(
                PinnedCollection.user_id == run.me
            )
        )
    )
    for row in run.rows("SELECT * FROM pinned_collections"):
        collection_id = run.collections.get(str(row["collection_id"]))
        if collection_id is None or collection_id in pinned:
            continue
        run.db.add(
            PinnedCollection(
                user_id=run.me,
                collection_id=collection_id,
                created_at=_time(row["created_at"]),
            )
        )
        pinned.add(collection_id)
