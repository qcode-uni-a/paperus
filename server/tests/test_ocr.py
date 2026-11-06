"""OCR of scanned pages and images (with a fake ML service)."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paperus import ocr
from paperus.ml import MLUnavailable
from paperus.models import File, OcrPage, OcrStatus, TextStatus
from paperus.pdf import png
from paperus.processing import process_file, reread_all
from paperus.storage import BlobStore
from tests.conftest import FakeML
from tests.pdfs import make_pdf

MODEL = "pp-ocrv6-small"
TYPED = "A typed first page about rain gauges, long enough to count as text."
# A typed page, then a scanned one (no text layer).
HALF_SCANNED = make_pdf([[TYPED], []])


def upload(
    client: TestClient, content: bytes, name: str = "scan.pdf", title: str = "Scan"
) -> uuid.UUID:
    item = client.post("/api/items", json={"metadata": {"title": title}}).json()
    kind = "application/pdf" if name.endswith(".pdf") else "image/png"
    file: dict[str, Any] = client.post(
        f"/api/items/{item['id']}/files", files={"upload": (name, content, kind)}
    ).json()
    return uuid.UUID(file["id"])


def status(db: Session, file_id: uuid.UUID) -> tuple[str, str | None]:
    db.expire_all()
    file = db.get(File, file_id)
    assert file is not None
    return file.text_status, file.ocr_status


def test_scanned_pages_are_read_once(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    file_id = upload(logged_in, HALF_SCANNED)
    assert process_file(db, blobs, file_id) is True
    # The typed page is searchable at once; the scan waits.
    assert status(db, file_id) == (TextStatus.DONE, OcrStatus.PENDING)
    assert ocr.waiting(db) == [file_id]
    # A copy of the same file shares its text and its wait.
    copy_id = upload(logged_in, HALF_SCANNED, title="Copy")
    assert process_file(db, blobs, copy_id) is True

    again = ocr.read_scans(db, blobs, fake_ml.client(), MODEL, file_id)
    assert set(again) == {file_id, copy_id}
    assert len(fake_ml.read) == 1 and fake_ml.read[0].startswith(b"\x89PNG")
    assert status(db, file_id) == (TextStatus.PENDING, OcrStatus.PENDING)
    for each in again:
        assert process_file(db, blobs, each) is False
        assert status(db, each) == (TextStatus.DONE, OcrStatus.DONE)
    assert ocr.waiting(db) == []

    hits = logged_in.get("/api/search", params={"q": "typewriter"}).json()
    assert {hit["file_id"] for hit in hits} == {str(file_id), str(copy_id)}
    assert {hit["page"] for hit in hits} == {2}
    item = logged_in.get(f"/api/items/{hits[0]['item_id']}").json()
    assert item["versions"][0]["files"][0]["ocr_status"] == "done"

    # Everything read again (e.g. after an update): the stored OCR text.
    reread_all(db)
    for each in again:
        assert process_file(db, blobs, each) is False
    assert status(db, file_id) == (TextStatus.DONE, OcrStatus.DONE)
    assert len(fake_ml.read) == 1


def test_scans_and_images_without_text(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    scan_id = upload(logged_in, make_pdf([[], []]))
    image = png(4, 2, bytes(range(8)), 4)
    image_id = upload(logged_in, image, name="notes.png", title="Notes")
    for file_id in (scan_id, image_id):
        assert process_file(db, blobs, file_id) is True
        assert status(db, file_id) == (TextStatus.NO_TEXT, OcrStatus.PENDING)
        for each in ocr.read_scans(db, blobs, fake_ml.client(), MODEL, file_id):
            process_file(db, blobs, each)
        assert status(db, file_id) == (TextStatus.DONE, OcrStatus.DONE)
    # Both pages of the scan, and the image as it is.
    assert len(fake_ml.read) == 3 and fake_ml.read[2] == image
    pages = db.scalar(select(func.count()).select_from(OcrPage))
    assert pages == 3


def test_ocr_off_and_on_again(
    admin: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    file_id = upload(admin, HALF_SCANNED)
    process_file(db, blobs, file_id, ocr=False)
    assert status(db, file_id) == (TextStatus.DONE, OcrStatus.SKIPPED)
    assert ocr.waiting(db) == []

    config = admin.get("/api/admin/config").json()
    assert config["ocr"] is True
    assert admin.put("/api/admin/config", json={**config, "ocr": False}).is_success
    admin.put("/api/admin/config", json={**config, "ocr": True})
    assert status(db, file_id) == (TextStatus.DONE, OcrStatus.PENDING)
    admin.put("/api/admin/config", json={**config, "ocr": False})
    assert status(db, file_id) == (TextStatus.DONE, OcrStatus.SKIPPED)
    unknown = {**config, "ocr_model": "nope"}
    assert admin.put("/api/admin/config", json=unknown).status_code == 422


def test_ml_down_or_refusing(
    logged_in: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    file_id = upload(logged_in, HALF_SCANNED)
    process_file(db, blobs, file_id)
    fake_ml.down = True
    with pytest.raises(MLUnavailable):
        ocr.read_scans(db, blobs, fake_ml.client(), MODEL, file_id)
    assert status(db, file_id) == (TextStatus.DONE, OcrStatus.PENDING)
    fake_ml.down = False
    # Not an OCR model: failed, the typed text stays searchable.
    assert ocr.read_scans(db, blobs, fake_ml.client(), "bge-m3", file_id) == []
    assert status(db, file_id) == (TextStatus.DONE, OcrStatus.FAILED)
    assert db.scalar(select(func.count()).select_from(OcrPage)) == 0
