"""A readable copy of the library on disk (Administration → Settings →
Storage template): every paper's files under names from a template, e.g.
``Chair/Lovelace_NatPhys_1843.pdf``, for browsing
or other programs. paperus keeps its own storage by content (SHA-256); the
copy is rebuilt from it every night and touches only files it wrote itself
(listed in ``.paperus-copy.json``)."""

import ctypes
import json
import os
import re
import shutil
import string
import sys
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import changes
from paperus.citations import citation_key_base, year_of
from paperus.library import citation_csl, preferred_version
from paperus.models import FileRole, Group, Item, Library, SystemSetting, User
from paperus.storage import BlobStore, FilesystemStore

if sys.platform != "win32":
    import fcntl

# Linux's ioctl for a copy-on-write clone of a whole file (Btrfs, XFS).
FICLONE = 0x40049409

# Short and sortable: Lovelace_NatPhys_1843, in a folder per owner.
DEFAULT_TEMPLATE = "{owner}/{first_author}_{journal}_{year}"
VARIABLES = {
    "owner": "whose it is: the person's username or the group's name",
    "year": "year of publication",
    "first_author": "the first author's family name",
    "authors": "“Lovelace”, “Lovelace and Babbage” or “Lovelace et al.”, as Zotero",
    "journal": (
        "the journal's short name without spaces (PhysRevLett), else its"
        " full name, the publisher or the kind of document"
    ),
    "journal_long": "the journal's full name (Physical Review Letters), as written",
    "title": "the title (shortened at a word to about 80 characters)",
    "type": "article, book, thesis, …",
    "doi": "the DOI (its slash becomes “_”)",
    "citekey": "the citation key, as in exports",
    "filename": "the uploaded file's own name, without extension",
    "role": "main, supplementary, slides, …",
}
MANIFEST = ".paperus-copy.json"
KEY = "readable_copy"
SEGMENT_LENGTH = 150
TITLE_LENGTH = 80
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_SPACES = re.compile(r"\s+")


class TemplateError(ValueError):
    pass


def check_template(template: str) -> str:
    """The template if every ``{…}`` is a known variable."""
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as error:
        raise TemplateError(f"the template has a stray brace: {error}") from error
    for _, name, spec, conversion in parsed:
        if name is None:
            continue
        if name not in VARIABLES:
            raise TemplateError(f"unknown variable {{{name}}}")
        if spec or conversion:
            raise TemplateError(f"{{{name}}} takes no format")
    if not any(name for _, name, _, _ in parsed):
        raise TemplateError("the template needs at least one variable, e.g. {title}")
    return template


def _clean(text: str) -> str:
    """One path segment: no slashes or characters Windows refuses."""
    text = unicodedata.normalize("NFC", text)
    text = _SPACES.sub(" ", _FORBIDDEN.sub(" ", text)).strip(" .")
    return text[:SEGMENT_LENGTH].rstrip(" .") or "_"


def _shorten(text: str, length: int) -> str:
    text = _SPACES.sub(" ", text).strip()
    if len(text) <= length:
        return text
    return text[:length].rsplit(" ", 1)[0].rstrip(" ,;:-")


def _journal(csl: dict[str, Any]) -> str:
    """Compact, e.g. "Phys. Rev. Lett." → "PhysRevLett"."""
    for key in ("container-title-short", "container-title", "publisher"):
        value = csl.get(key)
        if isinstance(value, list):
            value = value[0] if value else None
        if value:
            words = re.split(r"[\s.]+", unicodedata.normalize("NFC", str(value)))
            compact = "".join(w[:1].upper() + w[1:] for w in words if w)
            if compact:
                return compact[:60]
    kind = str(csl.get("type") or "document")
    return "preprint" if kind == "article" else kind


def _journal_long(csl: dict[str, Any]) -> str:
    for key in ("container-title", "container-title-short", "publisher"):
        value = csl.get(key)
        if isinstance(value, list):
            value = value[0] if value else None
        if value:
            return _shorten(str(value), TITLE_LENGTH)
    return _journal(csl)


def _family(name: dict[str, Any]) -> str:
    family = " ".join(
        filter(None, [name.get("non-dropping-particle"), name.get("family")])
    )
    return family or str(name.get("literal") or "")


def values_for(
    csl: dict[str, Any], owner: str, filename: str, role: str
) -> dict[str, str]:
    names = [_family(n) for n in (csl.get("author") or csl.get("editor") or [])]
    names = [n for n in names if n]
    authors = " and ".join(names) if len(names) <= 2 else f"{names[0]} et al."
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return {
        "owner": owner,
        "year": str(year_of(csl) or "n.d."),
        "first_author": names[0] if names else "Unknown",
        "authors": authors or "Unknown",
        "journal": _journal(csl),
        "journal_long": _journal_long(csl),
        "title": _shorten(str(csl.get("title") or "Untitled"), TITLE_LENGTH),
        "type": str(csl.get("type") or "document"),
        "doi": str(csl.get("DOI") or "no DOI").replace("/", "_"),
        "citekey": citation_key_base(csl),
        "filename": stem,
        "role": role,
    }


def render(template: str, values: dict[str, str], suffix: str) -> str:
    """The relative path: the template's folders, each value cleaned."""
    cleaned = {name: value.replace("/", " ") for name, value in values.items()}
    raw = template.format_map(cleaned).split("/")
    parts = [_clean(p) for p in raw if p.strip() not in ("", ".", "..")] or ["_"]
    return str(PurePosixPath(*parts)) + suffix


def _suffix(filename: str) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ""


@dataclass
class Wanted:
    path: str
    sha256: bytes
    size: int


def _owners(db: Session) -> dict[Any, str]:
    owners: dict[Any, str] = {}
    for library_id, username, group in db.execute(
        select(Library.id, User.username, Group.name)
        .outerjoin(User, User.id == Library.user_id)
        .outerjoin(Group, Group.id == Library.group_id)
    ):
        owners[library_id] = group or username or "unknown"
    return owners


def wanted(
    db: Session,
    template: str,
    *,
    limit: int | None = None,
    libraries: list[uuid.UUID] | None = None,
) -> list[Wanted]:
    """Every file of every paper (not in the trash; the preferred
    version's files), or of those in ``libraries``, and where it goes in
    the copy."""
    owners = _owners(db)
    taken: set[str] = set()
    found: list[Wanted] = []
    query = select(Item).where(Item.deleted_at.is_(None)).order_by(Item.id)
    if libraries is not None:
        query = query.where(Item.library_id.in_(libraries))
    if limit is not None:
        query = query.limit(limit)
    for item in db.scalars(query):
        version = preferred_version(item)
        if version is None:
            continue
        csl = citation_csl(item)
        for file in version.files:
            if file.deleted_at is not None:
                continue
            values = values_for(
                csl, owners.get(item.library_id, "unknown"), file.filename, file.role
            )
            path = render(template, values, "")
            # Several files of a paper: the others named after their role.
            if file.role != FileRole.MAIN and not re.search(
                r"\{(filename|role)\}", template
            ):
                path += f" ({file.role})"
            unique, number = path, 2
            while (unique + _suffix(file.filename)).lower() in taken:
                unique, number = f"{path} ({number})", number + 1
            final = unique + _suffix(file.filename)
            taken.add(final.lower())
            found.append(Wanted(final, file.blob_sha256, file.blob.size or 0))
    return found


class CopyReport(BaseModel):
    at: datetime
    cloned: int = 0
    """Of the files written, how many as clones: no space, edits apart."""
    linked: int = 0
    """As hard links: no space, but an edit changes the stored file."""
    change: int | None = None
    """The library's change number it was made from (``paperus.changes``):
    a later one means the copy is behind."""
    files: int = 0
    bytes: int = 0
    written: int = 0
    removed: int = 0
    error: str | None = None


@dataclass
class _Manifest:
    files: dict[str, str] = field(default_factory=dict)
    """Relative path → SHA-256 (hex) of what paperus wrote there."""


def _read_manifest(root: Path) -> _Manifest:
    try:
        data = json.loads((root / MANIFEST).read_text())
        return _Manifest(files=dict(data.get("files", {})))
    except (OSError, ValueError):
        return _Manifest()


def _write_manifest(root: Path, manifest: _Manifest) -> None:
    tmp = root / f"{MANIFEST}.tmp"
    tmp.write_text(json.dumps({"files": manifest.files}, indent=0, sort_keys=True))
    tmp.replace(root / MANIFEST)


def _clone(source: Path, target: Path) -> bool:
    """``target`` as a copy-on-write clone of ``source`` (APFS on macOS,
    Btrfs and XFS on Linux): it takes no space until one of them changes,
    and an edit to one leaves the other alone. False where the file system
    cannot (then a link or a copy)."""
    try:
        if sys.platform == "darwin":
            libc = ctypes.CDLL(None, use_errno=True)
            done = libc.clonefile(os.fsencode(source), os.fsencode(target), 0) == 0
            return done
        if sys.platform != "win32":
            with source.open("rb") as original, target.open("wb") as clone:
                fcntl.ioctl(clone.fileno(), FICLONE, original.fileno())
            return True
    except OSError:
        target.unlink(missing_ok=True)
    return False


def _place(blobs: BlobStore, sha256: bytes, target: Path, link: bool) -> str:
    """Write one file of the copy: ``cloned``, ``linked`` or ``copied``."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.paperus-tmp")
    tmp.unlink(missing_ok=True)
    if isinstance(blobs, FilesystemStore):
        if _clone(blobs.path(sha256), tmp):
            tmp.replace(target)
            return "cloned"
        if link:
            try:
                os.link(blobs.path(sha256), tmp)
                tmp.replace(target)
                return "linked"
            except OSError:
                pass  # another disk: copy instead
    with tmp.open("wb") as out:
        for chunk in blobs.iter_bytes(sha256):
            out.write(chunk)
    tmp.replace(target)
    return "copied"


def _remove(root: Path, relative: str) -> None:
    path = root / relative
    path.unlink(missing_ok=True)
    # Folders left empty go too (never the root itself).
    for parent in path.parents:
        if parent == root or root not in parent.parents:
            break
        try:
            parent.rmdir()
        except OSError:
            break


def sync(
    db: Session, blobs: BlobStore, root: Path, template: str, *, links: bool
) -> CopyReport:
    """Bring the copy in line with the library; saves the report."""
    report = CopyReport(at=datetime.now(UTC), change=changes.current_change(db))
    try:
        root.mkdir(parents=True, exist_ok=True)
        manifest = _read_manifest(root)
        files = wanted(db, template)
        keep: dict[str, str] = {}
        for entry in files:
            sha = entry.sha256.hex()
            target = root / entry.path
            if manifest.files.get(entry.path) != sha or not target.exists():
                how = _place(blobs, entry.sha256, target, links)
                report.written += 1
                report.cloned += int(how == "cloned")
                report.linked += int(how == "linked")
            keep[entry.path] = sha
            report.bytes += entry.size
        for relative in set(manifest.files) - set(keep):
            _remove(root, relative)
            report.removed += 1
        manifest.files = keep
        _write_manifest(root, manifest)
        report.files = len(keep)
    except OSError as error:
        report.error = str(error)
    save_report(db, report)
    return report


def remove_copy(db: Session, root: Path) -> CopyReport:
    """Delete every file paperus wrote into the copy (nothing else)."""
    report = CopyReport(at=datetime.now(UTC))
    manifest = _read_manifest(root)
    for relative in manifest.files:
        _remove(root, relative)
        report.removed += 1
    (root / MANIFEST).unlink(missing_ok=True)
    save_report(db, report)
    return report


def save_report(db: Session, report: CopyReport) -> None:
    value = report.model_dump(mode="json")
    db.execute(
        insert(SystemSetting)
        .values(key=KEY, value=value)
        .on_conflict_do_update(index_elements=["key"], set_={"value": value})
    )
    db.commit()


def last_report(db: Session) -> CopyReport | None:
    row = db.get(SystemSetting, KEY)
    return CopyReport.model_validate(row.value) if row else None


def free_space(root: Path) -> int | None:
    """Free bytes where the copy goes (its nearest existing folder)."""
    for path in (root, *root.parents):
        if path.exists():
            try:
                return shutil.disk_usage(path).free
            except OSError:
                return None
    return None
