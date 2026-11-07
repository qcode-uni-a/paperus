"""Reading files into passages: web pages, files read already, and a
lookup that fails without losing the text."""

import uuid
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from paperus import processing
from paperus.models import Chunk, File, FileChunk, TextStatus
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.pdfs import make_pdf
from tests.people import Person


def upload(person: Person, name: str, content: bytes, kind: str) -> uuid.UUID:
    item = person.add("Upload")
    file: dict[str, Any] = person.post(
        f"/api/items/{item['id']}/files", files={"upload": (name, content, kind)}
    ).json()
    return uuid.UUID(file["id"])


def passages(db: Session, file_id: uuid.UUID) -> list[str]:
    return list(
        db.scalars(
            select(Chunk.text)
            .join(FileChunk, FileChunk.chunk_sha256 == Chunk.sha256)
            .where(FileChunk.file_id == file_id)
            .order_by(FileChunk.position)
        )
    )


def test_a_web_page(client: TestClient, db: Session, blobs: BlobStore) -> None:
    ada = Person(client, db, "ada")
    page = b"<html><body><h1>Radar gaps</h1><p>Filled by <b>kriging</b>.</p></body>"
    file_id = upload(ada, "page.html", page, "text/html")
    assert process_file(db, blobs, file_id) is False
    [text] = passages(db, file_id)
    assert "Radar gaps" in text and "kriging" in text and "<" not in text
    # Read once: a second job finds nothing to do, as does one for no file.
    assert process_file(db, blobs, file_id) is False
    assert process_file(db, blobs, uuid.uuid4()) is False


def test_a_failed_lookup_keeps_the_text(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise RuntimeError("the registry answered nonsense")

    ada = Person(client, db, "ada")
    content = make_pdf([["Drought indices", "https://doi.org/10.1234/drought.5."]])
    uploaded = ada.post(
        "/api/uploads", files={"upload": ("drought.pdf", content, "application/pdf")}
    ).json()
    file_id = uuid.UUID(uploaded["file"]["id"])
    http = httpx2.Client(transport=httpx2.MockTransport(broken))
    process_file(db, blobs, file_id, http)
    db.expire_all()
    file = db.get(File, file_id)
    assert file is not None and file.text_status == TextStatus.DONE
    assert "Drought indices" in passages(db, file_id)[0]
    assert ada.get(f"/api/items/{uploaded['item_id']}").json()["title"] == "drought"


def test_reading_a_file_does_not_block_others_with_its_content(
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While the worker reads a file, another file with the same content can
    be added (the worker once locked the shared content too, and an upload
    of the same file deadlocked with it)."""
    ada = Person(client, db, "ada")
    page = b"<html><body><h1>Radar gaps</h1></body></html>"
    file_id = upload(ada, "page.html", page, "text/html")
    other = ada.add("Another paper")
    version_id = ada.get(f"/api/items/{other['id']}").json()["versions"][0]["id"]
    added: list[str] = []
    read = processing._read

    def read_while_someone_adds(db: Session, file: File, blobs: BlobStore) -> Any:  # noqa: ANN401
        # The worker holds its lock now; another connection adds a file with
        # the same content and must not have to wait.
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '2s'"))
            connection.execute(
                text(
                    "INSERT INTO files (id, version_id, blob_sha256, role, filename,"
                    " media_type, source, text_status, created_at)"
                    " VALUES (gen_random_uuid(), :version, :sha, 'main', 'copy.html',"
                    " 'text/html', 'upload', 'done', now())"
                ),
                {"version": version_id, "sha": file.blob_sha256},
            )
            added.append("ok")
        return read(db, file, blobs)

    monkeypatch.setattr(processing, "_read", read_while_someone_adds)
    assert process_file(db, blobs, file_id) is False
    assert added == ["ok"]
