"""Fluent mode's page layouts of PDFs (``paperus.page_layout``), stored once
per file content: made by the worker when a PDF is read, when the viewer
asks for one there is none of yet, and again for all after the layout code
changed (``page_layout.VERSION``), a few at a time in the background."""

import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import page_layout, pdf
from paperus.models import File, PageLayouts
from paperus.storage import BlobStore

log = logging.getLogger(__name__)

PDF = "application/pdf"


def make(db: Session, blobs: BlobStore, sha256: bytes) -> None:
    """Work out and store the layouts of a PDF's pages (none, if it cannot
    be read: then not tried again until the code changes). Commits."""
    known = db.get(PageLayouts, sha256)
    if known is not None and known.version == page_layout.VERSION:
        return
    try:
        with blobs.local_file(sha256) as path:
            pages = pdf.layouts(path)
    except (pdf.PdfError, FileNotFoundError) as error:
        log.warning("no page layouts for %s: %s", sha256.hex(), error)
        pages = []
    db.execute(
        insert(PageLayouts)
        .values(blob_sha256=sha256, version=page_layout.VERSION, pages=pages)
        .on_conflict_do_update(
            index_elements=[PageLayouts.blob_sha256],
            set_={"version": page_layout.VERSION, "pages": pages},
        )
    )
    db.commit()


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
