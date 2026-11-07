"""Running an import: finding the export in what was uploaded, reading it in
its format, adding it, and keeping the ``Import`` row up to date.

LaTeX sources (arXiv's ``.tar.gz`` or single gzipped ``.tex``, a zip of a
LaTeX project, a ``.bbl`` alone) bring their reference list: the ``.bbl``
(exactly the references the paper prints), else a ``thebibliography`` in the
``.tex``, else the ``.bib`` limited to the keys the ``.tex`` cites (a
``.bib`` often holds far more). Its papers go into a collection named after
the paper.
"""

import dataclasses
import gzip
import logging
import re
import tarfile
import uuid
import zipfile
import zlib
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx2
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from paperus import metadata
from paperus.access import Access
from paperus.identifiers import normalize_arxiv
from paperus.importing import Export, bbl, bibtex, csljson, references, ris, zotero
from paperus.importing.apply import Files as FileSource
from paperus.importing.apply import FolderFiles, NoFiles, ZipFiles, apply
from paperus.models import Blob, File, Import, ImportStatus, User
from paperus.storage import BlobStore

log = logging.getLogger(__name__)

READERS: dict[str, Callable[[str], Export]] = {
    "bibtex": bibtex.read,
    "ris": ris.read,
    "csl-json": csljson.read,
    "zotero-rdf": zotero.read,
    "bbl": bbl.read,
}
# File endings of the exports, in the order they are looked for in a zip.
ENDINGS = {
    ".bbl": "bbl",
    ".rdf": "zotero-rdf",
    ".bib": "bibtex",
    ".bibtex": "bibtex",
    ".ris": "ris",
    ".json": "csl-json",
}


class NotAnExport(ValueError):
    pass


# The export itself (not its files): far more than any real library needs,
# far less than a zip bomb would unpack to.
MAX_EXPORT_BYTES = 200 * 1024 * 1024
# Archives of LaTeX sources are read without unpacking them to disk; at
# most this many members and bytes are gone through (a figure-heavy arXiv
# source has a few hundred files and some 100 MB).
MAX_MEMBERS = 10_000
MAX_UNPACKED_BYTES = 2 * 1024**3
LATEX_ENDINGS = (".bbl", ".tex", ".bib", ".bibtex")
_THEBIBLIOGRAPHY = re.compile(r"\\begin\s*\{thebibliography\}")


def _decode(data: bytes) -> str:
    """Text in UTF-8, else Windows-1252; NUL characters (Postgres refuses
    them in text) dropped."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding).replace("\x00", "")
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1").replace("\x00", "")


def _too_large(size: int) -> NotAnExport:
    return NotAnExport(
        f"The export file is {size // 2**20} MB; at most "
        f"{MAX_EXPORT_BYTES // 2**20} MB can be read (files beside it may be larger)."
    )


def _guess(name: str, text: str) -> str:
    """The format from the file ending, else from the content."""
    ending = Path(name).suffix.lower()
    if ending in ENDINGS:
        return ENDINGS[ending]
    if "<rdf:RDF" in text[:5000]:
        return "zotero-rdf"
    if _THEBIBLIOGRAPHY.search(text) or "\\endentry" in text:
        return "bbl"
    start = text.lstrip()[:200]
    if start.startswith("@") or "\n@" in text[:5000]:
        return "bibtex"
    if start.startswith("TY  -"):
        return "ris"
    if start.startswith(("[", "{")):
        return "csl-json"
    raise NotAnExport(
        "This is not an export paperus can read: use Zotero RDF (.rdf), BibTeX "
        "(.bib), RIS (.ris) or CSL-JSON (.json), alone or in a zip with the "
        "files, or a LaTeX source (.tar.gz, .bbl)."
    )


@dataclass
class Opened:
    format: str
    text: str
    files: FileSource
    latex: bool = False
    """A LaTeX source or reference list: its papers go into a collection."""
    title: str | None = None
    """The paper's ``\\title``, in a LaTeX source."""
    cited: set[str] | None = None
    """The keys the LaTeX source cites, to pick them from its .bib."""


@contextmanager
def open_export(path: Path, name: str) -> Generator[tuple[str, str, FileSource]]:
    """(format, text, files) of an upload or a path on the server: a zip
    with the export and its files, a folder, or the export file alone."""
    with open_upload(path, name) as opened:
        yield opened.format, opened.text, opened.files


@contextmanager
def open_upload(path: Path, name: str) -> Generator[Opened]:
    """What :func:`open_export` reads, and LaTeX sources (see the module)."""
    if path.is_dir():
        candidates = sorted(
            p for p in path.rglob("*") if p.suffix.lower() in ENDINGS and p.is_file()
        )
        if not candidates:
            raise NotAnExport("No .rdf, .bib, .ris or .json file in the folder.")
        if candidates[0].stat().st_size > MAX_EXPORT_BYTES:
            raise _too_large(candidates[0].stat().st_size)
        text = _decode(candidates[0].read_bytes())
        yield Opened(_guess(candidates[0].name, text), text, FolderFiles(path))
        return
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if not n.endswith("/")]
            if _is_latex_project(names):
                yield _latex(_zip_members(archive, names))
                return
            exports = [
                n
                for ending in ENDINGS
                for n in names
                if n.lower().endswith(ending) and "/__macosx/" not in f"/{n.lower()}"
            ]
            if not exports:
                raise NotAnExport("No .rdf, .bib, .ris or .json file in the zip.")
            # The shallowest one: the export itself, not a file attached to a paper.
            chosen = min(exports, key=lambda n: n.count("/"))
            # The size the zip says, checked before unpacking; zipfile
            # unpacks no more than that (a zip lying about it fails).
            size = archive.getinfo(chosen).file_size
            if size > MAX_EXPORT_BYTES:
                raise _too_large(size)
            text = _decode(archive.read(chosen))
            yield Opened(_guess(chosen, text), text, ZipFiles(archive))
        return
    if _is_tar(path):
        yield _latex(_tar_members(path))
        return
    if _is_gzip(path):
        data = _gunzip(path)
        name = re.sub(r"\.gz$", "", name, flags=re.I)
    elif path.stat().st_size > MAX_EXPORT_BYTES:
        raise _too_large(path.stat().st_size)
    else:
        data = path.read_bytes()
    text = _decode(data)
    if _is_latex_file(name, text):
        yield _latex([(name, text)])
        return
    yield Opened(_guess(name, text), text, NoFiles())


def _is_latex_file(name: str, text: str) -> bool:
    ending = Path(name).suffix.lower()
    if ending in (".bbl", ".tex"):
        return True
    if ending in ENDINGS:
        return False
    return bool(
        _THEBIBLIOGRAPHY.search(text)
        or "\\endentry" in text
        or "\\documentclass" in text[:100_000]
    )


def _is_latex_project(names: list[str]) -> bool:
    """A zip of a LaTeX project rather than an export with its files: a
    .bbl or .tex no deeper than the shallowest export (an export's attached
    files may be .tex files, deeper down)."""
    latex = [n.count("/") for n in names if n.lower().endswith((".bbl", ".tex"))]
    exports = [
        n.count("/")
        for n in names
        if Path(n).suffix.lower() in ENDINGS
        and not n.lower().endswith(".bbl")
        and Path(n).name.lower() != "00readme.json"  # arXiv's processing notes
    ]
    return bool(latex) and (not exports or min(latex) <= min(exports))


def _zip_members(archive: zipfile.ZipFile, names: list[str]) -> list[tuple[str, str]]:
    """The LaTeX source's .tex, .bbl and .bib files, as text."""
    if len(names) > MAX_MEMBERS:
        raise _too_many()
    members, total = [], 0
    for name in names:
        if not name.lower().endswith(LATEX_ENDINGS):
            continue
        # The size the zip says; zipfile unpacks no more than that.
        total += archive.getinfo(name).file_size
        if total > MAX_EXPORT_BYTES:
            raise _too_large(total)
        members.append((name, _decode(archive.read(name))))
    return members


def _tar_members(path: Path) -> list[tuple[str, str]]:
    """The same from a tar archive (also gzipped, as arXiv's sources): read
    member by member, never unpacked to disk, so names like ``../x`` or links
    do no harm; sizes are checked before reading on."""
    members, total, unpacked = [], 0, 0
    try:
        with tarfile.open(path, "r:*") as archive:
            for count, member in enumerate(archive, 1):
                if count > MAX_MEMBERS:
                    raise _too_many()
                unpacked += member.size
                if unpacked > MAX_UNPACKED_BYTES:
                    raise NotAnExport(
                        f"The archive unpacks to more than "
                        f"{MAX_UNPACKED_BYTES // 2**30} GB."
                    )
                if not (
                    member.isfile() and member.name.lower().endswith(LATEX_ENDINGS)
                ):
                    continue
                total += member.size
                if total > MAX_EXPORT_BYTES:
                    raise _too_large(total)
                stream = archive.extractfile(member)  # a file: never None
                data = stream.read() if stream else b""
                members.append((member.name, _decode(data)))
    except (tarfile.TarError, EOFError, zlib.error, OSError) as error:
        raise NotAnExport(f"The archive could not be read: {error}") from error
    return members


def _is_tar(path: Path) -> bool:
    try:
        return tarfile.is_tarfile(path)
    except (EOFError, zlib.error, OSError):  # broken: refused when unpacked
        return False


def _too_many() -> NotAnExport:
    return NotAnExport(f"The archive holds more than {MAX_MEMBERS} files.")


def _is_gzip(path: Path) -> bool:
    with path.open("rb") as file:
        return file.read(2) == b"\x1f\x8b"


def _gunzip(path: Path) -> bytes:
    """A single gzipped file (arXiv's sources of one .tex), at most
    ``MAX_EXPORT_BYTES`` of it."""
    try:
        with gzip.open(path) as file:
            data = file.read(MAX_EXPORT_BYTES + 1)
    except (EOFError, zlib.error, OSError) as error:
        raise NotAnExport(f"The file could not be unpacked: {error}") from error
    if len(data) > MAX_EXPORT_BYTES:
        raise NotAnExport(
            f"The file unpacks to more than {MAX_EXPORT_BYTES // 2**20} MB."
        )
    return data


def _latex(members: list[tuple[str, str]]) -> Opened:
    """The reference list of a LaTeX source (see the module)."""
    # .tex files; a single file of another name (arXiv's gzipped ones) too.
    tex = [
        text
        for name, text in members
        if not name.lower().endswith((".bbl", ".bib", ".bibtex"))
    ]
    # The main document's title: the one with \documentclass, else any.
    main = sorted(tex, key=lambda text: "\\documentclass" not in text)
    title = next((t for text in main if (t := bbl.tex_title(text))), None)
    lists = [text for name, text in members if name.lower().endswith(".bbl")]
    lists = lists or [text for text in tex if _THEBIBLIOGRAPHY.search(text)]
    if lists:
        return Opened("bbl", "\n".join(lists), NoFiles(), latex=True, title=title)
    bib = [text for name, text in members if name.lower().endswith((".bib", ".bibtex"))]
    if bib:
        cited = bbl.cited_keys("\n".join(tex)) if tex else None
        return Opened(
            "bibtex", "\n".join(bib), NoFiles(), latex=True, title=title, cited=cited
        )
    raise NotAnExport(
        "No reference list in this LaTeX source: no .bbl or .bib file, and no "
        "thebibliography in a .tex file."
    )


def read_opened(opened: Opened) -> Export:
    """The export in what was opened; of a LaTeX source's .bib only the
    entries it cites."""
    export = READERS[opened.format](opened.text)
    if opened.cited is not None:
        export.papers = [
            p for p in export.papers if p.source_key.lower() in opened.cited
        ]
    return export


# arXiv's names: "arXiv:2401.12345" (imports by arXiv ID), "2401.12345v2.tar.gz".
_ARXIV_NAME = re.compile(
    r"^(?:arxiv[:_ -]?)?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)"
    r"(?:\.tar)?(?:\.gz|\.tgz|\.zip)?$",
    re.IGNORECASE,
)


def arxiv_in_name(name: str) -> str | None:
    """The arXiv ID an upload's name gives, without version."""
    found = _ARXIV_NAME.match(name.strip())
    if not found:
        return None
    return normalize_arxiv(found.group(1))  # the pattern admits only valid IDs


def _collection_name(opened: Opened, name: str, http: httpx2.Client | None) -> str:
    """The paper's title: arXiv's for an arXiv ID, else from the .tex; else
    the file name."""
    arxiv = arxiv_in_name(name)
    if arxiv and http is not None:
        try:
            csl, _ = metadata.lookup_doi(http, f"10.48550/arxiv.{arxiv}")
        except (metadata.DOINotFound, metadata.MetadataUnavailable):
            pass
        else:
            if (title := metadata.csl_title(csl)) != "(untitled)":
                return title
    if opened.title:
        return opened.title
    stem = re.sub(r"(\.(tar|gz|tgz|zip|bbl|tex))+$", "", name.strip(), flags=re.I)
    return stem or "References"


def run_import(
    db: Session,
    blobs: BlobStore,
    record: Import,
    *,
    path: Path,
    max_file_bytes: int,
    file_added: Callable[[uuid.UUID], None] = lambda file_id: None,
    http: httpx2.Client | None = None,
) -> None:
    """Run the import described by ``record`` from the export at ``path``;
    with ``http``, references from LaTeX sources are looked up online."""

    @contextmanager
    def read() -> Generator[tuple[Export, FileSource]]:
        with open_upload(path, record.filename) as opened:
            record.format = opened.format
            db.commit()  # the format shows while references are looked up
            export = read_opened(opened)
            if opened.format == "bbl":
                references.complete(export, http)
            if opened.latex and export.papers:
                into_collection(export, _collection_name(opened, record.filename, http))
            yield export, opened.files

    run_export(
        db,
        blobs,
        record,
        read,
        max_file_bytes=max_file_bytes,
        file_added=file_added,
    )


def into_collection(export: Export, name: str) -> None:
    """All the export's papers into a new collection of this name."""
    collection = (name,)
    export.collections.append(collection)
    for paper in export.papers:
        paper.collections.append(collection)


def run_export(
    db: Session,
    blobs: BlobStore,
    record: Import,
    read: Callable[[], AbstractContextManager[tuple[Export, FileSource]]],
    *,
    max_file_bytes: int,
    file_added: Callable[[uuid.UUID], None] = lambda file_id: None,
) -> None:
    """Add what ``read`` gives (an export and its files) for the person who
    started the import, keeping ``record`` up to date."""
    record.status = ImportStatus.RUNNING
    db.commit()
    user = db.get(User, record.user_id)
    try:
        if user is None or user.deactivated_at is not None:
            raise NotAnExport("The person who started the import cannot log in.")
        access = Access.of(db, user)
        with read() as (export, files):
            record.total = len(export.papers) + len(export.notes)
            db.commit()
            row_id = record.id

            def progress(done: int, total: int) -> None:
                # Every few papers: the page shows the progress.
                if done % 5 == 0 or done == total:
                    row = db.get(Import, row_id)
                    if row is not None:
                        row.done = done
                        db.commit()

            report = apply(
                db,
                blobs,
                access,
                export,
                files,
                owner=record.library_id,
                max_file_bytes=max_file_bytes,
                progress=progress,
                file_added=file_added,
            )
        record = db.get(Import, row_id) or record
        record.report = dataclasses.asdict(report)
        record.status = ImportStatus.DONE
    except Exception as error:
        db.rollback()
        log.warning("import %s failed", record.id, exc_info=True)
        record = db.get(Import, record.id) or record
        record.status = ImportStatus.FAILED
        record.error = (
            str(error)
            if isinstance(error, NotAnExport)
            else (f"The import stopped: {error}")
        )
    record.finished_at = datetime.now(UTC)
    upload, record.blob_sha256 = record.blob_sha256, None
    db.commit()
    if upload is not None:
        _forget_upload(db, blobs, upload)


def _forget_upload(db: Session, blobs: BlobStore, sha256: bytes) -> None:
    """Delete the uploaded export, unless something else stores the same
    bytes (e.g. the same zip imported as a paper's file, or imported again)."""
    used = db.scalar(select(File.id).where(File.blob_sha256 == sha256).limit(1))
    waiting = db.scalar(select(Import.id).where(Import.blob_sha256 == sha256).limit(1))
    if used is not None or waiting is not None:
        return
    db.execute(delete(Blob).where(Blob.sha256 == sha256))
    db.commit()
    blobs.delete(sha256)
