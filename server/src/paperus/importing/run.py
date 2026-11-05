"""Running an import: finding the export in what was uploaded, reading it in
its format, adding it, and keeping the ``Import`` row up to date."""

import dataclasses
import logging
import uuid
import zipfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from paperus.access import Access
from paperus.importing import Export, bibtex, csljson, ris
from paperus.importing.apply import Files as FileSource
from paperus.importing.apply import FolderFiles, NoFiles, ZipFiles, apply
from paperus.models import Import, ImportStatus, User
from paperus.storage import BlobStore

log = logging.getLogger(__name__)

READERS: dict[str, Callable[[str], Export]] = {
    "bibtex": bibtex.read,
    "ris": ris.read,
    "csl-json": csljson.read,
}
# File endings of the exports, in the order they are looked for in a zip.
ENDINGS = {".bib": "bibtex", ".bibtex": "bibtex", ".ris": "ris", ".json": "csl-json"}


class NotAnExport(ValueError):
    pass


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _guess(name: str, text: str) -> str:
    """The format from the file ending, else from the content."""
    ending = Path(name).suffix.lower()
    if ending in ENDINGS:
        return ENDINGS[ending]
    if ending == ".rdf" or "<rdf:RDF" in text[:2000]:
        raise NotAnExport(
            "Zotero RDF is not supported yet. In Zotero, export as BibTeX (with "
            "“Export Files”) for now."
        )
    start = text.lstrip()[:200]
    if start.startswith("@") or "\n@" in text[:5000]:
        return "bibtex"
    if start.startswith("TY  -"):
        return "ris"
    if start.startswith(("[", "{")):
        return "csl-json"
    raise NotAnExport(
        "This is not an export paperus can read: use BibTeX (.bib), RIS (.ris) "
        "or CSL-JSON (.json), alone or in a zip with the files."
    )


@contextmanager
def open_export(path: Path, name: str) -> Generator[tuple[str, str, FileSource]]:
    """(format, text, files) of an upload or a path on the server: a zip
    with the export and its files, a folder, or the export file alone."""
    if path.is_dir():
        candidates = sorted(
            p for p in path.rglob("*") if p.suffix.lower() in ENDINGS and p.is_file()
        )
        if not candidates:
            raise NotAnExport("No .bib, .ris or .json file in the folder.")
        text = _decode(candidates[0].read_bytes())
        yield _guess(candidates[0].name, text), text, FolderFiles(path)
        return
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if not n.endswith("/")]
            exports = [
                n
                for ending in ENDINGS
                for n in names
                if n.lower().endswith(ending) and "/__macosx/" not in f"/{n.lower()}"
            ]
            if not exports:
                raise NotAnExport("No .bib, .ris or .json file in the zip.")
            # The shallowest one: the export itself, not a file attached to a paper.
            chosen = min(exports, key=lambda n: n.count("/"))
            text = _decode(archive.read(chosen))
            yield _guess(chosen, text), text, ZipFiles(archive)
        return
    text = _decode(path.read_bytes())
    yield _guess(name, text), text, NoFiles()


def run_import(
    db: Session,
    blobs: BlobStore,
    record: Import,
    *,
    path: Path,
    max_file_bytes: int,
    file_added: Callable[[uuid.UUID], None] = lambda file_id: None,
) -> None:
    """Run the import described by ``record`` from the export at ``path``."""
    record.status = ImportStatus.RUNNING
    db.commit()
    user = db.get(User, record.user_id)
    try:
        if user is None or user.deactivated_at is not None:
            raise NotAnExport("The person who started the import cannot log in.")
        access = Access.of(db, user)
        with open_export(path, record.filename) as (format_, text, files):
            record.format = format_
            export = READERS[format_](text)
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
    record.blob_sha256 = None
    db.commit()
