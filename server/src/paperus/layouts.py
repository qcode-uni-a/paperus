"""Fluent mode's page layouts of PDFs (``paperus.page_layout``), stored once
per file content: made by the worker when a PDF is read (its passages are
cut from them), when the viewer asks for one there is none of yet, and
again for all after the layout code changed (``page_layout.VERSION``), a
few at a time in the background: then their passages are cut again too."""

import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import figures, page_layout, pdf
from paperus.models import File, PageLayouts
from paperus.storage import BlobStore

log = logging.getLogger(__name__)

PDF = "application/pdf"


def make(db: Session, blobs: BlobStore, sha256: bytes) -> pdf.Read | None:
    """Work out and store the layouts of a PDF's pages (none, if it cannot
    be read: then not tried again until the code changes). Commits. The
    PDF as read, if it was (not if its layouts were known)."""
    known = db.get(PageLayouts, sha256)
    if known is not None and known.version == page_layout.VERSION:
        return None
    try:
        with blobs.local_file(sha256) as path:
            read = pdf.read(path)
    except (pdf.PdfError, FileNotFoundError) as error:
        log.warning("no page layouts for %s: %s", sha256.hex(), error)
        read = None
    store(db, sha256, read.layouts if read else None)
    db.commit()
    return read


def store(
    db: Session, sha256: bytes, pages: list[page_layout.PageLayout] | None
) -> None:
    """Keep the layouts of a PDF's pages (``None``: it has none); its figures
    drawn from older ones go (drawn again from these)."""
    pages = pages or []
    figures.forget(db, sha256)
    db.execute(
        insert(PageLayouts)
        .values(blob_sha256=sha256, version=page_layout.VERSION, pages=pages)
        .on_conflict_do_update(
            index_elements=[PageLayouts.blob_sha256],
            set_={"version": page_layout.VERSION, "pages": pages},
        )
    )


def outdated(db: Session, limit: int = 50) -> list[bytes]:
    """PDFs outside the trash without layouts of this code's version, the
    most recently added first."""
    return list(
        db.scalars(
            select(File.blob_sha256)
            .outerjoin(PageLayouts, PageLayouts.blob_sha256 == File.blob_sha256)
            .where(
                File.media_type == PDF,
                File.deleted_at.is_(None),
                (PageLayouts.version.is_(None))
                | (PageLayouts.version != page_layout.VERSION),
            )
            .group_by(File.blob_sha256)
            .order_by(func.max(File.created_at).desc())
            .limit(limit)
        )
    )


def progress(db: Session) -> tuple[int, int]:
    """PDF contents outside the trash with layouts (and passages) of this
    code's version, of all."""
    active = (
        select(File.blob_sha256)
        .where(File.media_type == PDF, File.deleted_at.is_(None))
        .distinct()
        .subquery()
    )
    total = db.scalar(select(func.count()).select_from(active)) or 0
    current = (
        db.scalar(
            select(func.count())
            .select_from(active)
            .join(PageLayouts, PageLayouts.blob_sha256 == active.c.blob_sha256)
            .where(PageLayouts.version == page_layout.VERSION)
        )
        or 0
    )
    return current, total
