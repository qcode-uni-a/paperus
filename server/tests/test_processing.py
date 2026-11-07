"""Reading files into passages: web pages, files read already, and a
lookup that fails without losing the text."""

import uuid
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

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
