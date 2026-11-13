"""OCR: the text of scanned pages and images, read by the ML service.

Reading a file notes its pages without text (``processing``); this reads
them, one page at a time, keeps the text per page of the contents (so a
file read again, or a copy, needs no OCR), and has the files read again
with it.
"""

import logging
import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paperus import pdf
from paperus.ml import MLClient, MLRejected
from paperus.models import File, FileChunk, OcrPage, OcrStatus, TextStatus
from paperus.processing import IMAGE_TYPES, PDF, scanned
from paperus.storage import BlobStore
from paperus.trash import file_in_trash, file_outside_trash

log = logging.getLogger(__name__)


def waiting(db: Session, limit: int = 500) -> list[uuid.UUID]:
    """Files whose scanned pages wait for OCR (read otherwise already)."""
    return list(
        db.scalars(
            select(File.id)
            .where(
                File.ocr_status == OcrStatus.PENDING,
                File.text_status != TextStatus.PENDING,
                file_outside_trash(),
            )
            .order_by(File.id)
            .limit(limit)
        )
    )


def read_scans(
    db: Session, blobs: BlobStore, ml: MLClient, model: str, file_id: uuid.UUID
) -> list[uuid.UUID]:
    """Read the file's scanned pages with OCR, each saved as soon as it is
    read (an interruption loses one page at most); then every file with
    these contents is to be read again, with that text. Returns those files.
    ``MLUnavailable`` (to try again later) if no ML service answers.
    Files in the trash wait (the sweep takes them once restored); a file
    deleted meanwhile ends it quietly."""
    file = db.get(File, file_id)
    if file is None or file.ocr_status != OcrStatus.PENDING:
        return []
    if file_in_trash(db, file_id):
        log.info("OCR of file %s left for later: it is in the trash", file_id)
        return []
    sha256 = file.blob_sha256
    done = set(db.scalars(select(OcrPage.page).where(OcrPage.blob_sha256 == sha256)))
    try:
        with blobs.local_file(sha256) as path:
            if file.media_type == PDF:
                pages = [
                    index
                    for index, text in enumerate(pdf.pages(path))
                    if scanned(text) and index not in done
                ]
            else:
                pages = [] if 0 in done or file.media_type not in IMAGE_TYPES else [0]
            for index in pages:
                image = pdf.render(path, index) if file.media_type == PDF else None
                read = ml.ocr(image or path.read_bytes(), model=model)
                db.execute(
                    insert(OcrPage)
                    .values(
                        blob_sha256=sha256,
                        page=index,
                        text=read.text,
                        lines=read.lines,
                        width=read.width,
                        height=read.height,
                        model=model,
                    )
                    .on_conflict_do_nothing()
                )
                db.commit()
            log.info("OCR read %d pages of file %s", len(pages), file_id)
    except (FileNotFoundError, IntegrityError):
        # Deleted while being read (the trash emptied): its contents gone.
        db.rollback()
        if db.get(File, file_id) is None:
            log.info("OCR of file %s stopped: the file was deleted", file_id)
            return []
        raise
    except (MLRejected, pdf.PdfError) as error:
        # Not an image the service can read, or no OCR model by that name:
        # "Read again" tries once more (e.g. after changing the model).
        log.warning("OCR of file %s failed: %s", file_id, error)
        db.rollback()
        db.execute(
            update(File)
            .where(File.blob_sha256 == sha256, File.ocr_status == OcrStatus.PENDING)
            .values(ocr_status=OcrStatus.FAILED)
        )
        db.commit()
        return []
    copies = list(
        db.scalars(
            select(File.id).where(
                File.blob_sha256 == sha256,
                File.ocr_status == OcrStatus.PENDING,
                File.text_status != TextStatus.PENDING,
            )
        )
    )
    if copies:
        db.execute(delete(FileChunk).where(FileChunk.file_id.in_(copies)))
        db.execute(
            update(File)
            .where(File.id.in_(copies))
            .values(text_status=TextStatus.PENDING, text_error=None)
        )
    db.commit()
    return copies


def switch(db: Session, on: bool) -> None:
    """OCR switched on (the scans skipped so far wait for it) or off."""
    old, new = (
        (OcrStatus.SKIPPED, OcrStatus.PENDING)
        if on
        else (OcrStatus.PENDING, OcrStatus.SKIPPED)
    )
    db.execute(update(File).where(File.ocr_status == old).values(ocr_status=new))
