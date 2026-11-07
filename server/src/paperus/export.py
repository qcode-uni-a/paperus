"""Exports: everything a person can see, to take home.

An export is one or more ordinary zips (at most ``PART_LIMIT`` each) that,
unpacked into one place, give one folder::

    paperus-export-2026-11-07/
      library.sqlite   paperus' own tables, only the rows the person sees
      part.json        which export and part this zip is
      README.txt       what is where, in plain words
      files/           each file once, under a readable name

Part 1 holds ``library.sqlite`` as its first entry (then ``part.json``,
``README.txt`` and files until the limit); later parts hold ``part.json``
and files. The ``files`` table says which part each file is in. The
database mirrors the server's tables and columns (UUIDs and times as text,
JSON as text, booleans as 0/1), without what is derived or internal. See
docs/export.md; ``paperus.importing.paperus_export`` reads it back.

Everything is streamed: rows go to SQLite in batches, files are copied from
the store chunk by chunk into the zips, so memory stays the same whatever
the library's size.
"""

import json
import logging
import mimetypes
import re
import shutil
import sqlite3
import unicodedata
import uuid
import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from paperus import __version__, formats, organize
from paperus.access import Access, NotVisible
from paperus.config import Settings
from paperus.identifiers import Scheme
from paperus.importing import Export as ProgramExport
from paperus.importing import ExportedFile, ExportedNote, ExportedPaper
from paperus.library import KIND_PREFERENCE
from paperus.models import (
    Author,
    Authorship,
    Blob,
    Collection,
    CollectionItem,
    CollectionNote,
    Export,
    ExportStatus,
    Favourite,
    File,
    Group,
    Identifier,
    Item,
    ItemReference,
    ItemTag,
    Note,
    NoteItem,
    PinnedCollection,
    Tag,
    User,
    Version,
)
from paperus.organize import Rules
from paperus.readable import values_for
from paperus.storage import BlobStore
from paperus.system import load_config

log = logging.getLogger(__name__)

FORMAT = "paperus-export"
FORMAT_VERSION = 1
DATABASE = "library.sqlite"
PART_FILE = "part.json"
README = "README.txt"
FILES = "files"
PART_LIMIT = 2 * 1024**3
"""Bytes per zip at most (a file larger than this gets a zip of its own)."""
KEEP = timedelta(hours=24)
"""How long an export can be downloaded."""
FORGET = timedelta(days=7)
"""How long an expired export stays listed."""
BATCH = 500
STEM_LENGTH = 100
_PLACEHOLDER_PART = 32767
"""Written first and replaced by the real part: never needs more bytes."""


class Include(BaseModel):
    """What comes along with the papers (their versions, identifiers,
    favourites and archive marks always do); each can be left out. Left
    out, its tables stay empty."""

    notes: bool = True
    """Notes and their links to papers and collections."""
    tags: bool = True
    """Tags and keywords on the papers."""
    collections: bool = True
    """The collections (also smart ones), what they hold, pinned ones."""
    references: bool = True
    """The papers' reference lists."""
    authors: bool = True
    """The papers' authors as people (who is who: splits, merges, ids, and
    their affiliations on each paper)."""
    files: bool = True
    """The files themselves (their rows are kept, marked not included)."""
    archived: bool = True
    """Archived papers (left out entirely if not)."""


class Options(BaseModel):
    """What to export."""

    format: Literal["paperus", "zotero", "jabref", "mendeley"] = "paperus"
    """paperus' own (its tables as SQLite, complete, can be imported back),
    or a file for Zotero (RDF), JabRef (BibTeX) or Mendeley (RIS) beside
    the files."""
    owners: list[uuid.UUID] | None = None
    """Only these owners' things (library ids); all one can see if None."""
    collection_id: uuid.UUID | None = None
    """Only this collection (with those inside it), its papers and notes."""
    include: Include = Include()
    trash: bool = False
    """Also what is in the trash."""


# The database: paperus' tables with the same names and columns.

SCHEMA = """
CREATE TABLE paperus (
  format TEXT NOT NULL,
  format_version INTEGER NOT NULL,
  export_id TEXT NOT NULL,
  name TEXT NOT NULL,
  parts INTEGER NOT NULL,
  paperus_version TEXT NOT NULL,
  exported_at TEXT NOT NULL,
  exported_by TEXT NOT NULL,
  server_url TEXT,
  options TEXT NOT NULL
);
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL
);
CREATE TABLE owners (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('me', 'group')),
  name TEXT NOT NULL,
  role TEXT,
  group_id TEXT
);
CREATE TABLE items (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  library_id TEXT NOT NULL REFERENCES owners (id),
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  year INTEGER,
  file_wanted INTEGER NOT NULL,
  archived_at TEXT,
  references_source TEXT,
  overrides TEXT NOT NULL,
  added_by TEXT REFERENCES users (id),
  changed_at TEXT NOT NULL,
  deleted_at TEXT,
  deleted_by TEXT REFERENCES users (id)
);
CREATE TABLE versions (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  item_id TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  label TEXT,
  csl TEXT NOT NULL,
  metadata_source TEXT NOT NULL,
  pinned INTEGER NOT NULL,
  created_by TEXT REFERENCES users (id)
);
CREATE TABLE identifiers (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  version_id TEXT NOT NULL REFERENCES versions (id) ON DELETE CASCADE,
  scheme TEXT NOT NULL,
  value TEXT NOT NULL
);
CREATE TABLE files (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  version_id TEXT NOT NULL REFERENCES versions (id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  filename TEXT NOT NULL,
  media_type TEXT NOT NULL,
  source TEXT NOT NULL,
  uploaded_by TEXT REFERENCES users (id),
  deleted_at TEXT,
  deleted_by TEXT REFERENCES users (id),
  sha256 TEXT NOT NULL,
  size INTEGER NOT NULL,
  included INTEGER NOT NULL,
  path TEXT,
  part INTEGER
);
CREATE TABLE tags (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  library_id TEXT NOT NULL REFERENCES owners (id),
  name TEXT NOT NULL,
  color TEXT,
  description TEXT
);
CREATE TABLE item_tags (
  item_id TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
  tag_id TEXT NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  added_by TEXT REFERENCES users (id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (item_id, tag_id)
);
CREATE TABLE collections (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  library_id TEXT NOT NULL REFERENCES owners (id),
  name TEXT NOT NULL,
  description TEXT,
  parent_id TEXT REFERENCES collections (id) ON DELETE CASCADE,
  rules TEXT,
  created_by TEXT REFERENCES users (id)
);
CREATE TABLE collection_items (
  collection_id TEXT NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
  item_id TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
  added_by TEXT REFERENCES users (id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (collection_id, item_id)
);
CREATE TABLE notes (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  library_id TEXT NOT NULL REFERENCES owners (id),
  text TEXT NOT NULL,
  title TEXT NOT NULL,
  created_by TEXT REFERENCES users (id),
  changed_by TEXT REFERENCES users (id),
  changed_at TEXT NOT NULL,
  text_changed_at TEXT NOT NULL,
  deleted_at TEXT,
  deleted_by TEXT REFERENCES users (id)
);
CREATE TABLE note_items (
  note_id TEXT NOT NULL REFERENCES notes (id) ON DELETE CASCADE,
  item_id TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
  page INTEGER,
  added_by TEXT REFERENCES users (id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (note_id, item_id)
);
CREATE TABLE collection_notes (
  collection_id TEXT NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
  note_id TEXT NOT NULL REFERENCES notes (id) ON DELETE CASCADE,
  added_by TEXT REFERENCES users (id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (collection_id, note_id)
);
CREATE TABLE item_references (
  item_id TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  text TEXT NOT NULL,
  title TEXT,
  authors TEXT,
  year INTEGER,
  container TEXT,
  doi TEXT,
  arxiv TEXT,
  url TEXT,
  PRIMARY KEY (item_id, position)
);
CREATE TABLE favourites (
  user_id TEXT NOT NULL REFERENCES users (id),
  item_id TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, item_id)
);
CREATE TABLE pinned_collections (
  user_id TEXT NOT NULL REFERENCES users (id),
  collection_id TEXT NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, collection_id)
);
CREATE TABLE authors (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  orcid TEXT,
  openalex_id TEXT
);
CREATE TABLE authorships (
  item_id TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  author_id TEXT REFERENCES authors (id),
  written TEXT NOT NULL,
  source TEXT NOT NULL,
  affiliation TEXT,
  orcid TEXT,
  openalex_id TEXT,
  PRIMARY KEY (item_id, position)
);
"""

# Like the server's, created after the rows are in (faster).
INDEXES = """
CREATE INDEX ix_items_library_id ON items (library_id);
CREATE INDEX ix_items_year ON items (year);
CREATE INDEX ix_versions_item_id ON versions (item_id);
CREATE INDEX ix_identifiers_version_id ON identifiers (version_id);
CREATE INDEX ix_identifiers_scheme_value ON identifiers (scheme, value);
CREATE INDEX ix_files_version_id ON files (version_id);
CREATE INDEX ix_files_sha256 ON files (sha256);
CREATE UNIQUE INDEX ix_tags_library_name_lower ON tags (library_id, lower(name));
CREATE INDEX ix_item_tags_tag_id ON item_tags (tag_id);
CREATE INDEX ix_collections_library_id ON collections (library_id);
CREATE INDEX ix_collections_parent_id ON collections (parent_id);
CREATE INDEX ix_collection_items_item_id ON collection_items (item_id);
CREATE INDEX ix_notes_library_id ON notes (library_id);
CREATE INDEX ix_note_items_item_id ON note_items (item_id);
CREATE INDEX ix_collection_notes_note_id ON collection_notes (note_id);
CREATE INDEX ix_item_references_doi ON item_references (doi);
CREATE INDEX ix_item_references_arxiv ON item_references (arxiv);
CREATE INDEX ix_favourites_item_id ON favourites (item_id);
CREATE INDEX ix_pinned_collections_collection_id ON pinned_collections (collection_id);
"""

# Tables of later exports: an import reads them if there.
ADDED_LATER = ["authors", "authorships"]
TABLES = [
    "paperus",
    "users",
    "owners",
    "items",
    "versions",
    "identifiers",
    "files",
    "tags",
    "item_tags",
    "collections",
    "collection_items",
    "notes",
    "note_items",
    "collection_notes",
    "item_references",
    "favourites",
    "pinned_collections",
    *ADDED_LATER,
]


def time_text(value: datetime) -> str:
    """ISO 8601 in UTC: ``2026-11-07T10:00:00.123456Z``."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _value(value: object) -> object:
    """A value as SQLite stores it here."""
    match value:
        case uuid.UUID():
            return str(value)
        case datetime():
            return time_text(value)
        case bool():
            return int(value)
        case dict() | list():
            return json.dumps(value, ensure_ascii=False)
        case bytes():
            return value.hex()
    return value


# What the person exports.


@dataclass
class Owner:
    id: uuid.UUID
    kind: str
    """``me`` or ``group``."""
    name: str
    """"Me", or the group's path: "Uni/QCode Lab"."""
    role: str | None
    group_id: uuid.UUID | None


@dataclass
class Selection:
    owners: dict[uuid.UUID, Owner]
    items: dict[uuid.UUID, uuid.UUID]
    """Item → its owner."""
    notes: set[uuid.UUID]
    collections: set[uuid.UUID]
    tags: set[uuid.UUID]
    item_owners: set[uuid.UUID] = field(default_factory=set)
    """Owners of the items (to look up their rows by)."""
    collection_name: str | None = None


def owners_of(db: Session, access: Access) -> dict[uuid.UUID, Owner]:
    """Every owner the person reads: "Me" and their groups (by path)."""
    parents = dict(db.execute(select(Group.id, Group.parent_id)).all())
    names = dict(db.execute(select(Group.id, Group.name)).all())

    def path(group_id: uuid.UUID) -> str:
        parts: list[str] = []
        current: uuid.UUID | None = group_id
        while current is not None:
            parts.insert(0, names[current])
            current = parents.get(current)
        return "/".join(parts)

    found: dict[uuid.UUID, Owner] = {}
    if access.own_allowed:
        found[access.own_library] = Owner(access.own_library, "me", "Me", None, None)
    for group_id, library_id in sorted(
        access.group_libraries.items(), key=lambda pair: path(pair[0]).lower()
    ):
        found[library_id] = Owner(
            library_id,
            "group",
            path(group_id),
            access.roles[group_id].value,
            group_id,
        )
    return found


def choose(db: Session, access: Access, options: Options) -> Selection:
    """What the export holds, as the person sees it now."""
    readable = owners_of(db, access)
    chosen = (
        set(readable) if options.owners is None else set(readable) & set(options.owners)
    )

    def live(deleted_at: datetime | None) -> bool:
        return options.trash or deleted_at is None

    def wanted(deleted_at: datetime | None, archived_at: datetime | None) -> bool:
        return live(deleted_at) and (options.include.archived or archived_at is None)

    collection_name = None
    if options.collection_id is None:
        items = {
            item_id: library_id
            for item_id, library_id, deleted_at, archived_at in db.execute(
                select(
                    Item.id, Item.library_id, Item.deleted_at, Item.archived_at
                ).where(Item.library_id.in_(chosen))
            )
            if wanted(deleted_at, archived_at)
        }
        notes = {
            note_id
            for note_id, deleted_at in db.execute(
                select(Note.id, Note.deleted_at).where(Note.library_id.in_(chosen))
            )
            if live(deleted_at)
        }
        collections = set(
            db.scalars(select(Collection.id).where(Collection.library_id.in_(chosen)))
        )
        tags = set(db.scalars(select(Tag.id).where(Tag.library_id.in_(chosen))))
        owners = {k: owner for k, owner in readable.items() if k in chosen}
    else:
        collection = db.get(Collection, options.collection_id)
        if collection is None or not access.can_read(collection.library_id):
            raise NotVisible("collection not found")
        collection_name = collection.name
        collections = set(organize.descendants(db, collection.id))
        held: set[uuid.UUID] = set()
        for collection_id in collections:
            held.update(
                db.scalars(organize.item_ids_in(db, collection_id, nested=False))
            )
        items = {
            item_id: library_id
            for item_id, library_id, deleted_at, archived_at in db.execute(
                select(
                    Item.id, Item.library_id, Item.deleted_at, Item.archived_at
                ).where(Item.library_id.in_(chosen))
            )
            if item_id in held and wanted(deleted_at, archived_at)
        }
        filed = set(
            db.scalars(
                select(CollectionNote.note_id).where(
                    CollectionNote.collection_id.in_(collections)
                )
            )
        )
        about = {
            note_id
            for note_id, item_id in db.execute(
                select(NoteItem.note_id, NoteItem.item_id)
                .join(Note, Note.id == NoteItem.note_id)
                .where(Note.library_id.in_(chosen))
            )
            if item_id in items
        }
        notes = {
            note_id
            for note_id, deleted_at in db.execute(
                select(Note.id, Note.deleted_at).where(Note.library_id.in_(chosen))
            )
            if note_id in filed | about and live(deleted_at)
        }
        tags = set()
        owners = {collection.library_id: readable[collection.library_id]}
    include = options.include
    selection = Selection(
        owners=owners,
        items=items,
        notes=notes if include.notes else set(),
        collections=collections if include.collections else set(),
        tags=tags if include.tags else set(),
        collection_name=collection_name,
    )
    selection.item_owners = set(items.values())
    # Tags on the papers, of any owner the person reads (a group's
    # vocabulary on their own papers, their private tags on a group's).
    tagged = (
        db.execute(
            select(ItemTag.item_id, ItemTag.tag_id)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .join(Item, Item.id == ItemTag.item_id)
            .where(
                Item.library_id.in_(selection.item_owners),
                Tag.library_id.in_(readable),
            )
        )
        if include.tags
        else []
    )
    for item_id, tag_id in tagged:
        if item_id in items:
            selection.tags.add(tag_id)
    # Every owner something belongs to.
    used = set(selection.item_owners)
    used.update(
        db.scalars(select(Tag.library_id).where(Tag.id.in_(selection.tags)).distinct())
    )
    used.update(
        db.scalars(
            select(Collection.library_id)
            .where(Collection.id.in_(selection.collections))
            .distinct()
        )
    )
    used.update(
        db.scalars(
            select(Note.library_id).where(Note.id.in_(selection.notes)).distinct()
        )
    )
    for library_id in used:
        selection.owners.setdefault(library_id, readable[library_id])
    return selection


# Files: readable, unique names.

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_SPACES = re.compile(r"\s+")
_RESERVED = re.compile(r"(con|prn|aux|nul|com\d|lpt\d)(\..*)?", re.IGNORECASE)
_EXTENSIONS = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/html": ".html",
    "image/jpeg": ".jpg",
    "application/zip": ".zip",
}
# Already compressed: stored as they are (faster, and readable in place).
_DEFLATED_TYPES = re.compile(
    r"^(text/.*|application/(json|xml|xhtml\+xml|x-tex|x-latex|x-bibtex|"
    r"postscript|rtf|x-research-info-systems|csl\+json|javascript)|image/svg\+xml|"
    r"image/bmp|image/tiff|application/x-tar)$"
)


def safe_name(text: str, length: int = STEM_LENGTH) -> str:
    """A file name part safe on Windows, macOS and Linux."""
    text = unicodedata.normalize("NFC", text)
    text = _SPACES.sub(" ", _FORBIDDEN.sub(" ", text)).strip(" .")
    text = text[:length].rstrip(" .") or "_"
    return f"_{text}" if _RESERVED.fullmatch(text) else text


def extension(media_type: str, filename: str) -> str:
    """From the media type; the uploaded name's for unknown types."""
    known = _EXTENSIONS.get(media_type) or mimetypes.guess_extension(media_type)
    if known and known != ".bin":
        return known
    suffix = PurePosixPath(filename).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ""


def deflated(media_type: str) -> bool:
    """Whether a file of this type is worth compressing in the zip."""
    return bool(_DEFLATED_TYPES.match(media_type))


def file_stem(csl: dict[str, Any]) -> str:
    """ "<First author> <year> - <short title>"."""
    values = values_for(csl, owner="", filename="", role="")
    title = values["title"]
    if len(title) > 60:
        title = title[:60].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{values['first_author']} {values['year']} - {title}"


class Names:
    """Unique names in one folder (also where case does not count)."""

    def __init__(self) -> None:
        self.taken: set[str] = set()

    def add(self, stem: str, suffix: str) -> str:
        stem = safe_name(stem)
        number = 1
        while True:
            name = stem + (f" ({number})" if number > 1 else "") + suffix
            key = unicodedata.normalize("NFC", name).casefold()
            if key not in self.taken:
                self.taken.add(key)
                return name
            number += 1


_RANK = {kind.value: rank for rank, kind in enumerate(KIND_PREFERENCE)}


def _preferred_version(
    versions: list[tuple[uuid.UUID, str, bool, dict[str, Any]]],
) -> tuple[uuid.UUID, str, bool, dict[str, Any]]:
    """The version shown (as ``library.preferred_of``)."""
    for version in versions:
        if version[2]:
            return version
    newest_first = sorted(versions, key=lambda v: v[0], reverse=True)
    return min(newest_first, key=lambda v: _RANK.get(v[1], len(_RANK)))


# Splitting into parts.


def entry_cost(name: str, size: int, *, compressed: bool = False) -> int:
    """Bytes a zip entry takes at most: its data (deflate may add a little
    to data that does not compress) and headers with ZIP64 fields."""
    data = size + size // 500 + 64 if compressed else size
    return data + 2 * len(name.encode()) + 200


@dataclass
class PlannedFile:
    sha256: bytes
    name: str
    size: int
    compressed: bool


def plan(
    fixed: int, files: Iterable[PlannedFile], limit: int = PART_LIMIT
) -> list[int]:
    """The part of each file (from 1): part 1 holds ``fixed`` bytes (the
    database, README) and files until the limit, later parts only files; a
    file larger than the limit gets a part of its own."""
    parts: list[int] = []
    part, used = 1, fixed
    for file in files:
        cost = entry_cost(file.name, file.size, compressed=file.compressed)
        if used + cost > limit:
            # A new part takes the file, also one larger than the limit.
            part, used = part + 1, entry_cost(PART_FILE, 200)
        parts.append(part)
        used += cost
    return parts


def part_name(name: str, part: int, parts: int) -> str:
    return f"{name}.zip" if parts == 1 else f"{name}-part{part}-of-{parts}.zip"


def readme(
    name: str,
    *,
    exported_by: str,
    exported_at: datetime,
    server_url: str | None,
    counts: dict[str, int],
    parts: list[tuple[str, int]],
    missing: int,
    oversized: int,
) -> str:
    """README.txt: what is where, in plain words."""
    first = part_name(name, 1, len(parts))
    listing = "\n".join(
        f"  {part}: {files} {'file' if files == 1 else 'files'}"
        + (" and the database (library.sqlite)" if n == 0 else "")
        for n, (part, files) in enumerate(parts)
    )
    server = f" on {server_url}" if server_url else ""
    lines = [
        f"paperus export of {exported_by}{server}, {exported_at:%Y-%m-%d %H:%M} UTC",
        "",
        f"{counts['items']} papers, {counts['notes']} notes, "
        f"{counts['collections']} collections, {counts['files']} files.",
        "",
        "What is where",
        "",
        f"  {name}/library.sqlite   the library: papers, their versions,",
        "      identifiers and files, tags, collections, notes, reference lists,",
        "      favourites; only what you could see when exporting.",
        f"  {name}/files/           the files, each once, named",
        '      "<first author> <year> - <short title>". The table "files" says',
        "      which file belongs to which paper (columns path and part).",
        f"  {name}/README.txt       this text.",
        "",
    ]
    if len(parts) > 1:
        lines += [
            f"The export is in {len(parts)} zips; unpack them all into one folder to",
            "have everything in one place:",
            "",
            listing,
            "",
        ]
        if oversized:
            lines += [
                f"{oversized} {'file is' if oversized == 1 else 'files are'} larger"
                " than one zip may be and came in a zip of its own.",
                "",
            ]
    if missing:
        lines += [
            f"{missing} {'file was' if missing == 1 else 'files were'} missing on"
            " the server; their rows in the table files have no path.",
            "",
        ]
    lines += [
        "Opening the database",
        "",
        "library.sqlite is a SQLite database: open it with any SQLite tool, e.g.",
        "DB Browser for SQLite (sqlitebrowser.org), Datasette, or Python:",
        "",
        "  import sqlite3",
        '  db = sqlite3.connect("library.sqlite")',
        '  for title, year in db.execute("SELECT title, year FROM items"):',
        "      print(year, title)",
        "",
        "A plain SQL text of everything: sqlite3 library.sqlite .dump > library.sql",
        "Times are in UTC (ISO 8601), metadata in CSL-JSON (as text).",
        "",
        "Only the database, without unpacking the files",
        "",
        "It is the first entry of the first zip:",
        "",
        f'  unzip {first} "*/library.sqlite"',
        "",
        "or in Python:",
        "",
        "  import zipfile",
        f'  with zipfile.ZipFile("{first}") as z:',
        f'      z.extract("{name}/library.sqlite")',
        "",
        "Bringing it back",
        "",
        "paperus imports this export again (Import, choose all its zips): papers",
        "already there are recognized, nothing is added twice.",
        "The format is described in paperus' docs/export.md.",
        "",
    ]
    return "\n".join(lines)


# Writing the export.


@dataclass
class Part:
    name: str
    size: int
    files: int


@dataclass
class Written:
    parts: list[Part]
    counts: dict[str, int]


class _Database:
    """The SQLite file, written in batches."""

    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode = OFF")
        self.connection.execute("PRAGMA synchronous = OFF")
        self.connection.executescript(SCHEMA)
        self.users: set[uuid.UUID] = set()
        self.counts: dict[str, int] = {}

    def insert(self, table: str, rows: Iterable[Any]) -> int:
        """Rows in the table's column order; the people they name (who
        added or changed something) are listed in the table users."""
        columns = [
            row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")
        ]
        users = [n for n, column in enumerate(columns) if column in USER_COLUMNS]
        if table == "users":
            users = []
        count = 0
        batch: list[tuple[object, ...]] = []
        for row in rows:
            for position in users:
                if row[position] is not None:
                    self.users.add(row[position])
            batch.append(tuple(_value(value) for value in row))
            if len(batch) >= BATCH:
                self._flush(table, batch)
                count += len(batch)
                batch = []
        if batch:
            self._flush(table, batch)
            count += len(batch)
        self.counts[table] = self.counts.get(table, 0) + count
        return count

    def _flush(self, table: str, batch: list[tuple[object, ...]]) -> None:
        marks = ", ".join("?" * len(batch[0]))
        self.connection.executemany(f"INSERT INTO {table} VALUES ({marks})", batch)

    def close(self) -> None:
        self.connection.executescript(INDEXES)
        self.connection.commit()
        self.connection.close()


def _stream(db: Session, query: Select[Any]) -> Iterator[Any]:
    """Rows from the server in batches (a server-side cursor)."""
    yield from db.execute(query.execution_options(yield_per=1000))


# Each table's columns on the server, in the export's order.
COLUMNS: dict[str, list[Any]] = {
    "items": [
        Item.id,
        Item.created_at,
        Item.library_id,
        Item.type,
        Item.title,
        Item.year,
        Item.file_wanted,
        Item.archived_at,
        Item.references_source,
        Item.overrides,
        Item.added_by,
        Item.changed_at,
        Item.deleted_at,
        Item.deleted_by,
    ],
    "versions": [
        Version.id,
        Version.created_at,
        Version.item_id,
        Version.kind,
        Version.label,
        Version.csl,
        Version.metadata_source,
        Version.pinned,
        Version.created_by,
    ],
    "identifiers": [
        Identifier.id,
        Identifier.created_at,
        Identifier.version_id,
        Identifier.scheme,
        Identifier.value,
    ],
    "files": [
        File.id,
        File.created_at,
        File.version_id,
        File.role,
        File.filename,
        File.media_type,
        File.source,
        File.uploaded_by,
        File.deleted_at,
        File.deleted_by,
        File.blob_sha256,
    ],
    "tags": [
        Tag.id,
        Tag.created_at,
        Tag.library_id,
        Tag.name,
        Tag.color,
        Tag.description,
    ],
    "item_tags": [
        ItemTag.item_id,
        ItemTag.tag_id,
        ItemTag.source,
        ItemTag.added_by,
        ItemTag.created_at,
    ],
    "collections": [
        Collection.id,
        Collection.created_at,
        Collection.library_id,
        Collection.name,
        Collection.description,
        Collection.parent_id,
        Collection.rules,
        Collection.created_by,
    ],
    "collection_items": [
        CollectionItem.collection_id,
        CollectionItem.item_id,
        CollectionItem.added_by,
        CollectionItem.created_at,
    ],
    "notes": [
        Note.id,
        Note.created_at,
        Note.library_id,
        Note.text,
        Note.title,
        Note.created_by,
        Note.changed_by,
        Note.changed_at,
        Note.text_changed_at,
        Note.deleted_at,
        Note.deleted_by,
    ],
    "note_items": [
        NoteItem.note_id,
        NoteItem.item_id,
        NoteItem.page,
        NoteItem.added_by,
        NoteItem.created_at,
    ],
    "collection_notes": [
        CollectionNote.collection_id,
        CollectionNote.note_id,
        CollectionNote.added_by,
        CollectionNote.created_at,
    ],
    "item_references": [
        ItemReference.item_id,
        ItemReference.position,
        ItemReference.text,
        ItemReference.title,
        ItemReference.authors,
        ItemReference.year,
        ItemReference.container,
        ItemReference.doi,
        ItemReference.arxiv,
        ItemReference.url,
    ],
    "authors": [Author.id, Author.name, Author.orcid, Author.openalex_id],
    "authorships": [
        Authorship.item_id,
        Authorship.position,
        Authorship.author_id,
        Authorship.written,
        Authorship.source,
        Authorship.affiliation,
        Authorship.orcid,
        Authorship.openalex_id,
    ],
    "favourites": [Favourite.user_id, Favourite.item_id, Favourite.created_at],
    "pinned_collections": [
        PinnedCollection.user_id,
        PinnedCollection.collection_id,
        PinnedCollection.created_at,
    ],
}
USER_COLUMNS = {
    "added_by",
    "created_by",
    "changed_by",
    "deleted_by",
    "uploaded_by",
    "user_id",
}
"""Columns naming a person (listed in the table users)."""


class Seen:
    """What the person sees of each table, as rows streamed from the
    server (a few hundred at a time), with the columns of ``COLUMNS``.
    Shared by every export format."""

    def __init__(
        self, db: Session, access: Access, options: Options, selection: Selection
    ) -> None:
        self.db = db
        self.person = access.user.id
        self.username = access.user.username
        self.options = options
        self.selection = selection
        self.item_ids = selection.items
        self.owners = selection.item_owners

    def _of_items(
        self,
        table: str,
        *joins: tuple[Any, Any],
        keep: Callable[[Any], bool] = lambda row: True,
    ) -> Iterator[tuple[Any, ...]]:
        """Rows of a table hanging off the exported items."""
        columns = COLUMNS[table]
        query = select(*columns, Item.id.label("of_item"))
        for target, condition in joins:
            query = query.join(target, condition)
        query = query.where(Item.library_id.in_(self.owners)).order_by(*columns[:2])
        for row in _stream(self.db, query):
            if row.of_item in self.item_ids and keep(row):
                yield tuple(row)[:-1]

    def items(self) -> Iterator[Any]:
        query = (
            select(*COLUMNS["items"])
            .where(Item.library_id.in_(self.owners))
            .order_by(Item.created_at, Item.id)
        )
        return (row for row in _stream(self.db, query) if row.id in self.item_ids)

    def versions(self) -> Iterator[Any]:
        """By paper (``item_id``), oldest first."""
        query = (
            select(*COLUMNS["versions"])
            .join(Item, Item.id == Version.item_id)
            .where(Item.library_id.in_(self.owners))
            .order_by(Version.item_id, Version.id)
        )
        return (row for row in _stream(self.db, query) if row.item_id in self.item_ids)

    def identifiers(self) -> Iterator[Any]:
        return self._of_items(
            "identifiers",
            (Version, Version.id == Identifier.version_id),
            (Item, Item.id == Version.item_id),
        )

    def files(self) -> Iterator[Any]:
        """With ``of_item``, the paper; in the trash only with the trash."""
        query = (
            select(*COLUMNS["files"], Version.item_id.label("of_item"))
            .join(Version, Version.id == File.version_id)
            .join(Item, Item.id == Version.item_id)
            .where(Item.library_id.in_(self.owners))
            .order_by(Item.created_at, Item.id, File.id)
        )
        for row in _stream(self.db, query):
            if row.of_item in self.item_ids and (
                self.options.trash or row.deleted_at is None
            ):
                yield row

    def tags(self) -> Iterator[Any]:
        query = select(*COLUMNS["tags"]).where(Tag.id.in_(self.selection.tags))
        return _stream(self.db, query.order_by(Tag.created_at, Tag.id))

    def item_tags(self) -> Iterator[tuple[Any, ...]]:
        return self._of_items(
            "item_tags",
            (Item, Item.id == ItemTag.item_id),
            keep=lambda row: row.tag_id in self.selection.tags,
        )

    def collections(self) -> Iterator[Any]:
        """Parents before the collections inside them."""
        rows = list(
            self.db.execute(
                select(*COLUMNS["collections"]).where(
                    Collection.id.in_(self.selection.collections)
                )
            )
        )
        by_parent: dict[uuid.UUID | None, list[Any]] = {}
        for row in rows:
            parent = (
                row.parent_id if row.parent_id in self.selection.collections else None
            )
            by_parent.setdefault(parent, []).append(row)
        waiting = [None]
        while waiting:
            for row in sorted(
                by_parent.pop(waiting.pop(0), []), key=lambda r: (r.created_at, r.id)
            ):
                values = tuple(row)
                if row.parent_id not in self.selection.collections:
                    # At the top: the one above is not exported.
                    values = (*values[:5], None, *values[6:])
                yield values
                waiting.append(row.id)

    def collection_items(self) -> Iterator[Any]:
        query = select(*COLUMNS["collection_items"]).where(
            CollectionItem.collection_id.in_(self.selection.collections)
        )
        return (row for row in _stream(self.db, query) if row.item_id in self.item_ids)

    def notes(self) -> Iterator[Any]:
        query = (
            select(*COLUMNS["notes"])
            .where(Note.library_id.in_(self.selection.owners))
            .order_by(Note.created_at, Note.id)
        )
        return (
            row for row in _stream(self.db, query) if row.id in self.selection.notes
        )

    def note_items(self) -> Iterator[Any]:
        query = (
            select(*COLUMNS["note_items"])
            .join(Note, Note.id == NoteItem.note_id)
            .where(Note.library_id.in_(self.selection.owners))
        )
        return (
            row
            for row in _stream(self.db, query)
            if row.note_id in self.selection.notes and row.item_id in self.item_ids
        )

    def collection_notes(self) -> Iterator[Any]:
        query = select(*COLUMNS["collection_notes"]).where(
            CollectionNote.collection_id.in_(self.selection.collections)
        )
        return (
            row
            for row in _stream(self.db, query)
            if row.note_id in self.selection.notes
        )

    def item_references(self) -> Iterator[Any]:
        return self._of_items(
            "item_references", (Item, Item.id == ItemReference.item_id)
        )

    def authorships(self) -> Iterator[Any]:
        return self._of_items("authorships", (Item, Item.id == Authorship.item_id))

    def authors(self) -> Iterator[Any]:
        """The people of the exported papers, and those smart collections'
        rules name."""
        wanted = {row[2] for row in self.authorships() if row[2] is not None} | {
            author_id
            for (rules,) in self.db.execute(
                select(Collection.rules).where(
                    Collection.id.in_(self.selection.collections),
                    Collection.rules.is_not(None),
                )
            )
            for author_id in Rules.model_validate(rules or {}).authors
        }
        ordered = sorted(wanted)
        for start in range(0, len(ordered), 1000):
            yield from self.db.execute(
                select(*COLUMNS["authors"]).where(
                    Author.id.in_(ordered[start : start + 1000])
                )
            )

    def favourites(self) -> Iterator[Any]:
        """The person's own stars."""
        query = select(*COLUMNS["favourites"]).where(Favourite.user_id == self.person)
        return (row for row in self.db.execute(query) if row.item_id in self.item_ids)

    def pinned_collections(self) -> Iterator[Any]:
        """The person's own pins."""
        query = select(*COLUMNS["pinned_collections"]).where(
            PinnedCollection.user_id == self.person
        )
        return (
            row
            for row in self.db.execute(query)
            if row.collection_id in self.selection.collections
        )


def export_name(now: datetime, export_format: str = "paperus") -> str:
    """``paperus-export-2026-11-07-1530``, for other programs with theirs
    (``…-zotero``): the zips' top folder and their names."""
    suffix = "" if export_format == "paperus" else f"-{export_format}"
    return f"paperus-export-{now:%Y-%m-%d-%H%M}{suffix}"


def _shown(
    versions: list[Any], overrides: dict[uuid.UUID, dict[str, Any]]
) -> tuple[uuid.UUID, dict[str, Any]]:
    """A paper's shown version and its details (with manual edits)."""
    chosen = _preferred_version([(v.id, v.kind, v.pinned, v.csl) for v in versions])
    csl = dict(chosen[3])
    for key, value in overrides.get(versions[0].item_id, {}).items():
        if value is None:
            csl.pop(key, None)
        else:
            csl[key] = value
    return chosen[0], csl


class _Papers:
    """Each paper's shown details, gathered while its versions stream by
    (by paper): its file names, and for other programs its details."""

    def __init__(self, db: Session, selection: Selection) -> None:
        self.overrides = {
            item_id: value
            for item_id, value in db.execute(
                select(Item.id, Item.overrides).where(
                    Item.library_id.in_(selection.item_owners)
                )
            )
            if value and item_id in selection.items
        }
        self.stems: dict[uuid.UUID, str] = {}
        self.shown: dict[uuid.UUID, tuple[uuid.UUID, dict[str, Any]]] = {}

    def versions(self, rows: Iterator[Any], *, keep: bool = False) -> Iterator[Any]:
        """The rows as they come; ``keep``: also each paper's details."""
        paper: list[Any] = []

        def done() -> None:
            version_id, csl = _shown(paper, self.overrides)
            self.stems[paper[0].item_id] = file_stem(csl)
            if keep:
                self.shown[paper[0].item_id] = (version_id, csl)

        for row in rows:
            if paper and paper[0].item_id != row.item_id:
                done()
                paper.clear()
            paper.append(row)
            yield row
        if paper:
            done()


class _Files:
    """The files that go into the zips: each content once, named after its
    first paper."""

    def __init__(
        self, db: Session, blobs: BlobStore, selection: Selection, *, wanted: bool
    ) -> None:
        self.blobs = blobs
        self.wanted = wanted
        self.planned: dict[bytes, PlannedFile] = {}
        self.sizes = _blob_sizes(db, selection.item_owners)
        self.names = Names()
        self.missing = 0

    def add(self, row: Any, stem: str) -> PlannedFile | None:  # noqa: ANN401 (a row)
        """The file in the zips (None: left out, or missing on the server)."""
        sha = row.blob_sha256
        known = self.planned.get(sha)
        if known is not None or not self.wanted:
            return known
        if not self.blobs.exists(sha):
            log.warning("export: the contents of file %s are missing", row.id)
            self.missing += 1
            return None
        if row.role != "main":
            stem = f"{stem[: STEM_LENGTH - 20]} ({row.role})"
        known = self.planned[sha] = PlannedFile(
            sha,
            self.names.add(stem, extension(row.media_type, row.filename)),
            self.sizes.get(sha, 0),
            deflated(row.media_type),
        )
        return known


def write_export(
    db: Session,
    blobs: BlobStore,
    access: Access,
    options: Options,
    folder: Path,
    *,
    export_id: uuid.UUID,
    server_url: str | None = None,
    part_limit: int = PART_LIMIT,
    progress: Callable[[int, int], None] = lambda done, total: None,
) -> Written:
    """Write the export's zips into ``folder`` (which must exist); returns
    the parts. Reads from one snapshot of the database (callers start a
    REPEATABLE READ transaction for that)."""
    now = datetime.now(UTC)
    name = export_name(now, options.format)
    selection = choose(db, access, options)
    seen = Seen(db, access, options, selection)
    work = folder / "work"
    work.mkdir()
    try:
        if options.format != "paperus":
            return _for_program(
                db,
                blobs,
                access,
                options,
                selection,
                seen,
                folder,
                name=name,
                now=now,
                export_id=export_id,
                server_url=server_url,
                part_limit=part_limit,
                progress=progress,
            )
        return _paperus(
            db,
            blobs,
            access,
            options,
            selection,
            seen,
            folder,
            name=name,
            now=now,
            export_id=export_id,
            server_url=server_url,
            part_limit=part_limit,
            progress=progress,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _paperus(
    db: Session,
    blobs: BlobStore,
    access: Access,
    options: Options,
    selection: Selection,
    seen: "Seen",
    folder: Path,
    *,
    name: str,
    now: datetime,
    export_id: uuid.UUID,
    server_url: str | None,
    part_limit: int,
    progress: Callable[[int, int], None],
) -> Written:
    """paperus' own: library.sqlite and the files."""
    database_path = folder / "work" / DATABASE
    out = _Database(database_path)
    out.insert(
        "owners",
        ((o.id, o.kind, o.name, o.role, o.group_id) for o in selection.owners.values()),
    )
    out.insert("items", seen.items())
    papers = _Papers(db, selection)
    out.insert("versions", papers.versions(seen.versions()))
    out.insert("identifiers", seen.identifiers())
    files = _Files(db, blobs, selection, wanted=options.include.files)

    def file_rows() -> Iterator[tuple[Any, ...]]:
        for row in seen.files():
            known = files.add(row, papers.stems.get(row.of_item, "Untitled"))
            yield (
                *tuple(row)[:-1],
                files.sizes.get(row.blob_sha256, 0),
                int(known is not None),
                f"{FILES}/{known.name}" if known else None,
                _PLACEHOLDER_PART if known else None,
            )

    out.insert("files", file_rows())
    for table in (
        "tags",
        "item_tags",
        "collections",
        "collection_items",
        "notes",
        "note_items",
        "collection_notes",
        *(["item_references"] if options.include.references else []),
        *(["authors", "authorships"] if options.include.authors else []),
        "favourites",
        "pinned_collections",
    ):
        out.insert(table, getattr(seen, table)())
    out.users.add(access.user.id)
    out.insert(
        "users",
        db.execute(select(User.id, User.username).where(User.id.in_(out.users))),
    )

    # Which file goes into which part. The database, its "part" column not
    # filled in yet: filling it in never makes it larger (see
    # _PLACEHOLDER_PART); the paperus row and the indexes are allowed for.
    ordered = list(files.planned.values())
    out.connection.commit()
    database_size = database_path.stat().st_size * 2 + 64 * 1024
    assigned = plan(
        entry_cost(DATABASE, database_size, compressed=True) + _FIXED,
        ordered,
        part_limit,
    )
    count = max(assigned, default=1)
    out.connection.executemany(
        "UPDATE files SET part = ? WHERE sha256 = ?",
        [
            (part, file.sha256.hex())
            for part, file in zip(assigned, ordered, strict=True)
        ],
    )
    counts = {
        "items": len(selection.items),
        "notes": len(selection.notes),
        "collections": len(selection.collections),
        "files": len(ordered),
    }
    out.insert(
        "paperus",
        [
            (
                FORMAT,
                FORMAT_VERSION,
                export_id,
                name,
                count,
                __version__,
                now,
                access.user.username,
                server_url,
                {
                    **options.model_dump(mode="json"),
                    "collection_name": selection.collection_name,
                },
            )
        ],
    )
    out.close()
    by_part = _by_part(assigned, ordered)
    text = readme(
        name,
        exported_by=access.user.username,
        exported_at=now,
        server_url=server_url,
        counts=counts,
        parts=[(part_name(name, n, count), len(by_part[n])) for n in by_part],
        missing=files.missing,
        oversized=_oversized(ordered, part_limit),
    )
    parts = _zips(
        folder,
        blobs,
        name=name,
        now=now,
        export_id=export_id,
        contents="paperus",
        # First, so the database alone is quick to take out.
        first=[(DATABASE, database_path.read_bytes, True)],
        readme_text=text,
        by_part=by_part,
        progress=progress,
    )
    return Written(parts=parts, counts=counts)


# README, part.json and room for the written file's name: part 1's share
# besides the database or the written file.
_FIXED = entry_cost(README, 64 * 1024, compressed=True) + entry_cost(PART_FILE, 200)


def _by_part(
    assigned: list[int], ordered: list[PlannedFile]
) -> dict[int, list[PlannedFile]]:
    by_part: dict[int, list[PlannedFile]] = {
        n: [] for n in range(1, max(assigned, default=1) + 1)
    }
    for part, file in zip(assigned, ordered, strict=True):
        by_part[part].append(file)
    return by_part


def _oversized(ordered: list[PlannedFile], part_limit: int) -> int:
    return sum(1 for file in ordered if entry_cost(file.name, file.size) > part_limit)


def _zips(
    folder: Path,
    blobs: BlobStore,
    *,
    name: str,
    now: datetime,
    export_id: uuid.UUID,
    contents: str,
    first: list[tuple[str, Callable[[], bytes], bool]],
    readme_text: str,
    by_part: dict[int, list[PlannedFile]],
    progress: Callable[[int, int], None],
) -> list[Part]:
    """Write the zips: part 1 with ``first`` (name, its bytes, whether to
    compress), part.json, README.txt and files; later parts part.json and
    files."""
    count = len(by_part)
    done, total = 0, sum(len(files) for files in by_part.values()) + 1
    progress(done, total)
    parts: list[Part] = []
    stamp = (now.year, now.month, now.day, now.hour, now.minute, now.second)
    for n, files_here in by_part.items():
        target = folder / part_name(name, n, count)
        with zipfile.ZipFile(target, "w", allowZip64=True) as archive:
            if n == 1:
                for member, data, compressed in first:
                    archive.writestr(
                        _entry(f"{name}/{member}", stamp, compressed=compressed),
                        data(),
                    )
            marker = {
                "format": FORMAT,
                "format_version": FORMAT_VERSION,
                "contents": contents,
                "export": str(export_id),
                "name": name,
                "part": n,
                "parts": count,
            }
            archive.writestr(
                _entry(f"{name}/{PART_FILE}", stamp, compressed=False),
                json.dumps(marker, indent=2) + "\n",
            )
            if n == 1:
                archive.writestr(
                    _entry(f"{name}/{README}", stamp, compressed=True),
                    readme_text.replace("\n", "\r\n"),  # for Windows' Notepad too
                )
                done += 1
                progress(done, total)
            for file in files_here:
                entry = _entry(
                    f"{name}/{FILES}/{file.name}", stamp, compressed=file.compressed
                )
                entry.file_size = file.size
                with archive.open(entry, "w") as stream:
                    for chunk in blobs.iter_bytes(file.sha256):
                        stream.write(chunk)
                done += 1
                progress(done, total)
        parts.append(Part(target.name, target.stat().st_size, len(files_here)))
    return parts


# For other programs (Zotero, JabRef, Mendeley): the import's common form
# the other way round, written by ``paperus.formats``.

PROGRAMS = {
    "zotero": "Zotero",
    "jabref": "JabRef",
    "mendeley": "Mendeley",
}
CANNOT_HOLD: dict[str, dict[str, str]] = {
    "zotero": {
        "references": "Zotero RDF has no reference lists",
        "authors": "Zotero RDF has authors as names only",
    },
    "jabref": {
        "references": "BibTeX has no reference lists",
        "authors": "BibTeX has authors as names only",
    },
    "mendeley": {
        "references": "RIS has no reference lists",
        "collections": "RIS has no collections",
        "authors": "RIS has authors as names only",
    },
}
"""What each program's format cannot hold, and why (for the website)."""


def _collection_paths(
    db: Session, selection: Selection, seen: "Seen"
) -> dict[uuid.UUID, tuple[str, ...]]:
    """Each collection's path of names, under its owner's name when several
    owners are exported ("QCode Lab/Thesis"; a group's own name, its path
    where two have the same; the person's username for their own)."""
    rows = list(seen.collections())  # parents first
    if not rows:
        return {}
    owners = {row[2] for row in rows}
    prefix: dict[uuid.UUID, tuple[str, ...]] = {o: () for o in owners}
    if len(selection.owners) > 1:
        short = {
            o.id: o.name.rsplit("/", 1)[-1] if o.kind == "group" else ""
            for o in selection.owners.values()
        }
        for owner_id in owners:
            owner = selection.owners[owner_id]
            if owner.kind == "me":
                prefix[owner_id] = (seen.username,)
            elif list(short.values()).count(short[owner_id]) > 1:
                prefix[owner_id] = (owner.name.replace("/", " / "),)
            else:
                prefix[owner_id] = (short[owner_id],)
    paths: dict[uuid.UUID, tuple[str, ...]] = {}
    for row in rows:
        parent = paths.get(row[5]) if row[5] else None
        paths[row[0]] = (*(parent or prefix[row[2]]), row[3])
    return paths


def program_export(
    db: Session,
    selection: Selection,
    seen: "Seen",
    files: _Files,
) -> ProgramExport:
    """What the person sees, in the import's common form; files at
    ``files/<name>`` (planned in ``files``)."""
    options = seen.options
    papers = _Papers(db, selection)
    for _ in papers.versions(seen.versions(), keep=True):
        pass
    shown_versions = {version_id for version_id, _ in papers.shown.values()}
    identifiers: dict[uuid.UUID, list[tuple[Scheme, str]]] = {}
    for row in seen.identifiers():
        if row[2] in shown_versions:
            try:
                identifiers.setdefault(row[2], []).append((Scheme(row[3]), row[4]))
            except ValueError:
                continue
    exported: dict[uuid.UUID, ExportedPaper] = {}
    for row in seen.items():
        version_id, csl = papers.shown.get(row.id, (None, {}))
        exported[row.id] = ExportedPaper(
            csl=csl,
            identifiers=identifiers.get(version_id, []) if version_id else [],
            source_key=row.title,
        )
    tags = {row[0]: row[3] for row in seen.tags()}
    for row in seen.item_tags():
        paper, name = exported.get(row[0]), tags.get(row[1])
        if paper is None or name is None:
            continue
        if row[2] == "automatic":
            paper.keywords.append(name)
        else:
            paper.tags.append(name)
    paths = _collection_paths(db, selection, seen)
    for row in seen.collection_items():
        if row.collection_id in paths:
            exported[row.item_id].collections.append(paths[row.collection_id])
    # Smart collections: the papers matching them now.
    for collection_id in paths:
        collection = db.get(Collection, collection_id)
        if collection is not None and collection.rules is not None:
            for item_id in db.scalars(
                organize.item_ids_in(db, collection_id, nested=False)
            ):
                if item_id in exported:
                    exported[item_id].collections.append(paths[collection_id])
    for row in seen.files():
        known = files.add(row, papers.stems.get(row.of_item, "Untitled"))
        if known is not None:
            exported[row.of_item].files.append(
                ExportedFile(
                    f"{FILES}/{known.name}",
                    row.media_type,
                    None if row.role == "main" else row.role,
                )
            )
    notes: dict[uuid.UUID, str] = {row.id: row.text for row in seen.notes()}
    linked: set[uuid.UUID] = set()
    for row in seen.note_items():
        exported[row.item_id].notes.append(notes[row.note_id])
        linked.add(row.note_id)
    filed: dict[uuid.UUID, list[tuple[str, ...]]] = {}
    for row in seen.collection_notes():
        if row.collection_id in paths:
            filed.setdefault(row.note_id, []).append(paths[row.collection_id])
    result = ProgramExport(format=options.format)
    result.papers = list(exported.values())
    result.notes = [
        ExportedNote(text, filed.get(note_id, []))
        for note_id, text in notes.items()
        if note_id not in linked
    ]
    result.collections = list(paths.values())
    return result


def _for_program(
    db: Session,
    blobs: BlobStore,
    access: Access,
    options: Options,
    selection: Selection,
    seen: "Seen",
    folder: Path,
    *,
    name: str,
    now: datetime,
    export_id: uuid.UUID,
    server_url: str | None,
    part_limit: int,
    progress: Callable[[int, int], None],
) -> Written:
    """A file for another program (paperus.rdf, .bib, .ris), its README and
    the files."""
    files = _Files(db, blobs, selection, wanted=options.include.files)
    written = formats.WRITERS[options.format](
        program_export(db, selection, seen, files)
    )
    ordered = list(files.planned.values())
    assigned = plan(
        entry_cost(written.filename, len(written.content), compressed=True) + _FIXED,
        ordered,
        part_limit,
    )
    by_part = _by_part(assigned, ordered)
    count = len(by_part)
    program = PROGRAMS[options.format]
    lines = [
        f"paperus export for {program} of {access.user.username}"
        + (f" on {server_url}" if server_url else "")
        + f", {now:%Y-%m-%d %H:%M} UTC",
        "",
        f"{len(selection.items)} papers, {len(selection.notes)} notes, "
        f"{len(ordered)} files: {written.filename} and the folder files/.",
        "",
    ]
    if count > 1:
        lines += [
            f"The export is in {count} zips; unpack them all into one folder:",
            "",
            *(
                f"  {part_name(name, n, count)}: {len(by_part[n])} "
                + ("file" if len(by_part[n]) == 1 else "files")
                for n in by_part
            ),
            "",
        ]
    if files.missing:
        lines += [f"Files missing on the server: {files.missing}.", ""]
    if written.warnings:
        lines += ["What the file cannot hold:", ""]
        lines += [f"  - {warning}" for warning in written.warnings] + [""]
    lines += [written.readme.strip(), ""]
    parts = _zips(
        folder,
        blobs,
        name=name,
        now=now,
        export_id=export_id,
        contents=options.format,
        first=[
            (
                written.filename,
                lambda: written.content,
                True,
            )
        ],
        readme_text="\n".join(lines),
        by_part=by_part,
        progress=progress,
    )
    counts = {
        "items": len(selection.items),
        "notes": len(selection.notes),
        "collections": len(selection.collections),
        "files": len(ordered),
    }
    return Written(parts=parts, counts=counts)


def _entry(
    name: str, stamp: tuple[int, int, int, int, int, int], *, compressed: bool
) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, date_time=stamp)
    entry.compress_type = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
    entry.external_attr = 0o644 << 16
    return entry


def _blob_sizes(db: Session, owners: set[uuid.UUID]) -> dict[bytes, int]:
    return dict(
        db.execute(
            select(Blob.sha256, Blob.size)
            .join(File, File.blob_sha256 == Blob.sha256)
            .join(Version, Version.id == File.version_id)
            .join(Item, Item.id == Version.item_id)
            .where(Item.library_id.in_(owners))
            .distinct()
        ).all()
    )


# Before exporting: how much it would be.


class Estimate(BaseModel):
    items: int
    notes: int
    collections: int
    files: int
    """Files with their contents, each content once (0 without files)."""
    files_bytes: int
    size: int
    """About how many bytes the zips take together."""
    parts: int
    """How many zips (at most ``PART_LIMIT`` bytes each)."""


def estimate(
    db: Session, access: Access, options: Options, part_limit: int = PART_LIMIT
) -> Estimate:
    selection = choose(db, access, options)
    items = selection.items
    contents: dict[bytes, PlannedFile] = {}
    if options.include.files:
        for item_id, sha, size, media_type, deleted_at in db.execute(
            select(
                Version.item_id,
                Blob.sha256,
                Blob.size,
                File.media_type,
                File.deleted_at,
            )
            .join(File, File.version_id == Version.id)
            .join(Blob, Blob.sha256 == File.blob_sha256)
            .join(Item, Item.id == Version.item_id)
            .where(Item.library_id.in_(selection.item_owners))
        ):
            if item_id in items and (options.trash or deleted_at is None):
                # Names are about this long ("Lovelace 1843 - Notes on …").
                contents.setdefault(
                    sha, PlannedFile(sha, "x" * 70, size, deflated(media_type))
                )
    note_bytes = sum(
        length or 0
        for note_id, length in db.execute(
            select(Note.id, func.length(Note.text)).where(
                Note.library_id.in_(selection.owners)
            )
        )
        if note_id in selection.notes
    )
    # Rows of a paper with its versions, identifiers, tags: a few kB.
    database = 3000 * len(items) + 2 * note_bytes + 500 * len(selection.notes)
    fixed = entry_cost(DATABASE, database // 3) + entry_cost(README, 4000)
    files = list(contents.values())
    assigned = plan(fixed, files, part_limit)
    files_bytes = sum(file.size for file in files)
    return Estimate(
        items=len(items),
        notes=len(selection.notes),
        collections=len(selection.collections),
        files=len(files),
        files_bytes=files_bytes,
        size=fixed + files_bytes,
        parts=max(assigned, default=1),
    )


# The job, and tidying up.


class ExportError(Exception):
    pass


def folder_of(settings: Settings, export_id: uuid.UUID) -> Path:
    return settings.exports_folder / str(export_id)


def run(
    sessions: Callable[[], Session],
    blobs: BlobStore,
    settings: Settings,
    export_id: uuid.UUID,
    *,
    part_limit: int = PART_LIMIT,
) -> None:
    """Write the export ``export_id`` asked for, keeping its row up to date."""
    with sessions() as db:
        record = db.get(Export, export_id)
        # Running: retried after its worker stopped; it starts again.
        if record is None or record.status not in (
            ExportStatus.WAITING,
            ExportStatus.RUNNING,
        ):
            return
        record.status = ExportStatus.RUNNING
        record.done = record.total = 0
        user = db.get(User, record.user_id)
        options = Options.model_validate(record.options)
        server_url = load_config(db, settings).public_url
        db.commit()
        folder = folder_of(settings, export_id)
        partial = folder.with_name(folder.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)

        def progress(done: int, total: int) -> None:
            # In a session of its own: the export reads from one snapshot.
            with sessions() as other:
                other.execute(
                    update(Export)
                    .where(Export.id == export_id)
                    .values(done=done, total=total)
                )
                other.commit()

        try:
            if user is None or user.deactivated_at is not None:
                raise ExportError("The person who asked for it cannot log in.")
            # Everything from one consistent snapshot.
            db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            access = Access.of(db, user)
            written = write_export(
                db,
                blobs,
                access,
                options,
                partial,
                export_id=export_id,
                server_url=str(server_url).rstrip("/") if server_url else None,
                part_limit=part_limit,
                progress=progress,
            )
            db.commit()
            shutil.rmtree(folder, ignore_errors=True)
            partial.rename(folder)
            record = db.get_one(Export, export_id)
            record.status = ExportStatus.DONE
            record.parts = [vars(part) for part in written.parts]
            record.size = sum(part.size for part in written.parts)
            record.expires_at = datetime.now(UTC) + KEEP
        except Exception as error:
            db.rollback()
            log.warning("export %s failed", export_id, exc_info=True)
            shutil.rmtree(partial, ignore_errors=True)
            record = db.get_one(Export, export_id)
            record.status = ExportStatus.FAILED
            record.error = (
                str(error)
                if isinstance(error, ExportError | NotVisible)
                else f"The export stopped: {error}"
            )
        record.finished_at = datetime.now(UTC)
        db.commit()


def part_path(settings: Settings, record: Export, part: int) -> Path | None:
    """The zip of one part (from 1), while it lasts."""
    if record.status != ExportStatus.DONE or not 1 <= part <= len(record.parts):
        return None
    path = folder_of(settings, record.id) / str(record.parts[part - 1]["name"])
    return path if path.is_file() else None


def delete(db: Session, settings: Settings, record: Export) -> None:
    shutil.rmtree(folder_of(settings, record.id), ignore_errors=True)
    db.delete(record)


def remove_expired(db: Session, settings: Settings) -> int:
    """Delete the zips of exports older than a day (they stay listed as
    expired for a week), and leftovers of interrupted ones; how many."""
    now = datetime.now(UTC)
    removed = 0
    for record in db.scalars(
        select(Export).where(
            Export.status == ExportStatus.DONE, Export.expires_at < now
        )
    ):
        shutil.rmtree(folder_of(settings, record.id), ignore_errors=True)
        record.status = ExportStatus.EXPIRED
        removed += 1
    for record in db.scalars(
        select(Export).where(
            Export.status.in_([ExportStatus.EXPIRED, ExportStatus.FAILED]),
            Export.created_at < now - KEEP - FORGET,
        )
    ):
        delete(db, settings, record)
    db.commit()
    root = settings.exports_folder
    if root.is_dir():
        known = {
            str(export_id)
            for export_id in db.scalars(
                select(Export.id).where(
                    Export.status.in_(
                        [ExportStatus.WAITING, ExportStatus.RUNNING, ExportStatus.DONE]
                    )
                )
            )
        }
        for path in root.iterdir():
            if path.name.removesuffix(".partial") not in known:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
    return removed
