from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paperus.config import Settings
from paperus.models import Blob

PDF_BYTES = b"%PDF-1.7\n" + b"x" * 5000 + b"\n%%EOF\n"


def add_item(client: TestClient, title: str) -> str:
    response = client.post("/api/items", json={"metadata": {"title": title}})
    assert response.status_code == 201
    item_id: str = response.json()["id"]
    return item_id


def upload(
    client: TestClient,
    item_id: str,
    content: bytes = PDF_BYTES,
    filename: str = "paper.pdf",
    media_type: str = "application/pdf",
    **form: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/items/{item_id}/files",
        files={"upload": (filename, content, media_type)},
        data=form,
    )
    assert response.status_code == 201, response.text
    result: dict[str, object] = response.json()
    return result


@pytest.fixture
def item_id(logged_in: TestClient) -> str:
    return add_item(logged_in, "A")


def test_upload_and_download(logged_in: TestClient, item_id: str) -> None:
    file = upload(logged_in, item_id, role="supplementary")
    assert file["media_type"] == "application/pdf"
    assert file["size"] == len(PDF_BYTES)
    assert file["role"] == "supplementary"
    assert file["source"] == "upload"
    assert file["filename"] == "paper.pdf"

    response = logged_in.get(f"/api/files/{file['id']}/content")
    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in response.headers

    [version] = logged_in.get(f"/api/items/{item_id}").json()["versions"]
    assert version["files"] == [file]
    assert file["version_id"] == version["id"]

    second = logged_in.post(
        f"/api/versions/{version['id']}/files",
        files={"upload": ("slides.pdf", PDF_BYTES, "application/pdf")},
        data={"role": "slides"},
    )
    assert second.status_code == 201
    assert second.json()["role"] == "slides"


def test_same_content_is_stored_once(
    logged_in: TestClient,
    item_id: str,
    db: Session,
    settings: Settings,
) -> None:
    other_item = add_item(logged_in, "B")
    first = upload(logged_in, item_id)
    second = upload(logged_in, other_item, filename="copy.pdf")
    assert first["id"] != second["id"]
    assert first["sha256"] == second["sha256"]
    assert db.scalar(select(func.count()).select_from(Blob)) == 1
    stored = [p for p in (settings.storage_path / "blobs").rglob("*") if p.is_file()]
    assert len(stored) == 1
    assert not any((settings.storage_path / "tmp").iterdir())


def test_rejects_login_page_saved_as_pdf(logged_in: TestClient, item_id: str) -> None:
    response = logged_in.post(
        f"/api/items/{item_id}/files",
        files={
            "upload": ("paper.pdf", b"<html>Please log in</html>", "application/pdf")
        },
    )
    assert response.status_code == 422


def test_other_file_types(logged_in: TestClient, item_id: str) -> None:
    file = upload(logged_in, item_id, b"# Notes\n", "notes.md", "text/markdown")
    assert file["media_type"] == "text/markdown"
    file = upload(
        logged_in, item_id, b"\x00\x01", "data.bin", "application/octet-stream"
    )
    assert file["media_type"] == "application/octet-stream"


def test_upload_errors(logged_in: TestClient, item_id: str) -> None:
    files = {"upload": ("paper.pdf", PDF_BYTES, "application/pdf")}
    unknown = "00000000-0000-7000-8000-000000000000"
    assert logged_in.post(f"/api/items/{unknown}/files", files=files).status_code == 404
    response = logged_in.post(
        f"/api/items/{item_id}/files", files=files, data={"role": "final"}
    )
    assert response.status_code == 422
    assert logged_in.get(f"/api/files/{unknown}/content").status_code == 404


def test_too_large(
    logged_in: TestClient, item_id: str, settings: Settings, tmp_path: Path
) -> None:
    settings.max_upload_bytes = 100
    response = logged_in.post(
        f"/api/items/{item_id}/files",
        files={"upload": ("paper.pdf", PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 413
    assert not any((settings.storage_path / "tmp").iterdir())


def test_files_need_login(client: TestClient) -> None:
    unknown = "00000000-0000-7000-8000-000000000000"
    files = {"upload": ("paper.pdf", PDF_BYTES, "application/pdf")}
    assert client.post(f"/api/items/{unknown}/files", files=files).status_code == 401
    assert client.get(f"/api/files/{unknown}/content").status_code == 401


def test_uploaded_html_cannot_run_scripts(logged_in: TestClient, item_id: str) -> None:
    page = b"<script>fetch('/api/items')</script>"
    file = upload(logged_in, item_id, page, "notes.html", "text/html")
    response = logged_in.get(f"/api/files/{file['id']}/content")
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_lists_name_file_types(logged_in: TestClient, item_id: str) -> None:
    """For the icon in lists: the PDF first; none without files."""
    [listed] = logged_in.get("/api/items").json()
    assert listed["files"] == []
    for name, data, media_type in (
        ("notes.md", b"# Notes", "text/markdown"),
        ("paper.pdf", PDF_BYTES, "application/pdf"),
        ("more.md", b"# More", "text/markdown"),
    ):
        response = logged_in.post(
            f"/api/items/{item_id}/files",
            files={"upload": (name, data, media_type)},
            data={"role": "main" if name == "paper.pdf" else "other"},
        )
        assert response.status_code == 201, response.text
    [listed] = logged_in.get("/api/items").json()
    names = [(f["filename"], f["media_type"]) for f in listed["files"]]
    assert names == [
        ("paper.pdf", "application/pdf"),
        ("notes.md", "text/markdown"),
        ("more.md", "text/markdown"),
    ]
    opened = logged_in.get(f"/api/files/{listed['files'][0]['id']}/content")
    assert opened.content == PDF_BYTES
