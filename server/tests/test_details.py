"""A paper's details (title and abstract) as a search passage
(``paperus.details``)."""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus.embedding import details_missing_embeddings, embed_details
from paperus.models import Chunk, Item, ItemChunk
from paperus.processing import process_file
from paperus.storage import BlobStore
from paperus.trash import collect_garbage
from tests.conftest import FakeML
from tests.pdfs import make_pdf

MODEL = "bge-m3"


def add_item(client: TestClient, title: str) -> str:
    response = client.post("/api/items", json={"metadata": {"title": title}})
    assert response.status_code == 201, response.text
    item_id: str = response.json()["id"]
    return item_id


def search(client: TestClient, q: str, **params: str) -> list[dict[str, Any]]:
    response = client.get("/api/search", params={"q": q, **params})
    assert response.status_code == 200, response.text
    hits: list[dict[str, Any]] = response.json()
    return hits


def details_of(db: Session, item_id: str) -> str:
    text = db.scalar(
        select(Chunk.text)
        .join(ItemChunk, ItemChunk.chunk_sha256 == Chunk.sha256)
        .where(ItemChunk.item_id == uuid.UUID(item_id))
    )
    db.rollback()
    return text or ""


def test_found_by_its_title_without_a_file(logged_in: TestClient) -> None:
    item_id = add_item(logged_in, "Memristors from zirconium oxide")
    [hit] = search(logged_in, "zirconium", mode="keyword")
    assert hit["kind"] == "details"
    assert hit["item_id"] == item_id
    assert hit["passage_id"] == f"{item_id}#details"
    assert hit["file_id"] is None
    assert "<mark>zirconium</mark>" in hit["snippet"]


def test_details_follow_the_title_and_abstract(
    logged_in: TestClient, db: Session
) -> None:
    item_id = add_item(logged_in, "Rainfall records")
    assert details_of(db, item_id) == "Rainfall records"

    item = db.get(Item, uuid.UUID(item_id))
    assert item is not None
    item.title = "Snowfall records"
    item.abstract = "Daily depths from 120 stations."
    db.commit()
    assert details_of(db, item_id) == (
        "Snowfall records\n\nDaily depths from 120 stations."
    )
    assert search(logged_in, "rainfall", mode="keyword") == []
    [hit] = search(logged_in, "stations", mode="keyword")
    assert hit["kind"] == "details"


def test_details_take_the_abstract_the_paper_shows(
    logged_in: TestClient, db: Session
) -> None:
    """Its details' own abstract (as text), a manual edit of it, a new
    version's."""
    response = logged_in.post(
        "/api/items",
        json={
            "metadata": {
                "title": "Glacier retreat",
                "abstract": "<jats:p>Ice loss in the Alps.</jats:p>",
            }
        },
    )
    item_id = response.json()["id"]
    assert details_of(db, item_id) == "Glacier retreat\n\nIce loss in the Alps."

    response = logged_in.put(
        f"/api/items/{item_id}/overrides",
        json={"abstract": "Ice loss since 1850."},
        headers={"If-Match": response.headers["ETag"]},
    )
    assert response.status_code == 200, response.text
    assert details_of(db, item_id) == "Glacier retreat\n\nIce loss since 1850."
    [hit] = search(logged_in, "1850", mode="keyword")
    assert hit["kind"] == "details"

    other = add_item(logged_in, "Glacier records")
    response = logged_in.post(
        f"/api/items/{other}/versions",
        json={
            "kind": "published",
            "metadata": {"title": "Glacier records", "abstract": "Lengths."},
        },
    )
    assert response.status_code == 201, response.text
    assert details_of(db, other) == "Glacier records\n\nLengths."


def test_a_title_match_comes_before_a_mention(
    logged_in: TestClient, db: Session, blobs: BlobStore
) -> None:
    """A paper about SPEI (in its title) before one that mentions it."""
    other = add_item(logged_in, "Drought in Bavaria")
    file = logged_in.post(
        f"/api/items/{other}/files",
        files={
            "upload": (
                "paper.pdf",
                make_pdf([["We computed the SPEI at a 3-month scale."]]),
                "application/pdf",
            )
        },
    ).json()
    process_file(db, blobs, uuid.UUID(file["id"]))
    about = add_item(logged_in, "The SPEI, a drought index")
    hits = search(logged_in, "SPEI", mode="keyword")
    assert [h["item_id"] for h in hits] == [about, other]
    assert [h["kind"] for h in hits] == ["details", "paper"]


def test_trashed_papers_are_not_found_by_their_details(logged_in: TestClient) -> None:
    item_id = add_item(logged_in, "Gauges in the Alps")
    logged_in.delete(f"/api/items/{item_id}")
    assert search(logged_in, "gauges", mode="keyword") == []


def test_details_are_embedded(
    logged_in: TestClient, db: Session, fake_ml: FakeML
) -> None:
    item_id = add_item(logged_in, "Interpolating missing rain data")
    assert len(details_missing_embeddings(db, MODEL)) == 1
    assert embed_details(db, fake_ml.client(), MODEL) == 1
    assert details_missing_embeddings(db, MODEL) == []
    [hit] = search(logged_in, "gaps in the records", mode="meaning")
    assert hit["item_id"] == item_id
    assert hit["matched"] == ["meaning"]


def test_garbage_collection_keeps_details(
    logged_in: TestClient, db: Session, blobs: BlobStore
) -> None:
    item_id = add_item(logged_in, "Rain gauges compared")
    collect_garbage(db, blobs)
    assert details_of(db, item_id) == "Rain gauges compared"
