"""First start: checking a backup's files before restoring it."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from paperus.backup import create_backup
from paperus.config import Settings
from paperus.storage import BlobStore
from tests.pdfs import make_pdf


def test_check_before_restoring(
    logged_in: TestClient, engine: Engine, blobs: BlobStore, settings: Settings
) -> None:
    item = logged_in.post(
        "/api/items", json={"metadata": {"title": "With its PDF"}}
    ).json()
    upload = logged_in.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("paper.pdf", make_pdf([["Rain"]]), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    manifest = create_backup(engine, blobs, settings.backup_path, with_files=False)
    # Once set up, there is nothing to check.
    set_up = logged_in.get("/api/setup/restore-check", params={"name": manifest.name})
    assert set_up.status_code == 409

    # A new installation with the backup folder, but not the files.
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE users, items, libraries CASCADE"))
    for sha256, _, _ in list(blobs.iter_stored()):
        blobs.delete(sha256)
    logged_in.cookies.clear()
    unknown = logged_in.get("/api/setup/restore-check", params={"name": "nope"})
    assert unknown.status_code == 404
    check = logged_in.get("/api/setup/restore-check", params={"name": manifest.name})
    assert check.status_code == 200
    assert check.json() == {
        "with_files": False,
        "needed": 1,
        "in_storage": 0,
        "from_backup": 0,
        "missing": 1,
        "affected": ["With its PDF"],
        "affected_count": 1,
        "extra": 0,
    }
