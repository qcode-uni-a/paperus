"""Reordering the best search hits with a reranker (fake ML service: it
puts passages with FakeML.FAVOURITE first)."""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.config import Settings
from paperus.embedding import embed_file
from paperus.jobs import send_ml_config
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.conftest import FakeML
from tests.test_meaning import MODEL, add_file, search

PAPERS = {
    "Rain gauges": b"Rain gauges measured the rain every week near the lake.",
    "Rain radar": b"Weather radar estimates rain over the whole valley.",
    "Light rain": b"Drizzle is light rain with very small drops.",
}


def library(client: TestClient, db: Session, blobs: BlobStore, ml: FakeML) -> None:
    for title, text in PAPERS.items():
        file_id = uuid.UUID(add_file(client, title, text)["id"])
        process_file(db, blobs, file_id)
        embed_file(db, ml.client(), MODEL, file_id)


def set_rerank(
    admin: TestClient, rerank: str, model: str = "bge-reranker-v2-m3"
) -> int:
    config = admin.get("/api/admin/config").json()
    response = admin.put(
        "/api/admin/config", json={**config, "rerank": rerank, "rerank_model": model}
    )
    return response.status_code


def test_auto_reranks_only_on_a_gpu(
    admin: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    library(admin, db, blobs, fake_ml)
    hits, _ = search(admin, "rain")
    assert not any(h["reranked"] for h in hits)
    assert fake_ml.reranked == []

    fake_ml.device = "cuda"
    app = admin.app
    assert isinstance(app, FastAPI)
    app.state.ml._device = None  # asked again (cached for a minute)
    hits, _ = search(admin, "rain", per_item="1", limit="2")
    assert [h["item_title"] for h in hits] == ["Light rain", hits[1]["item_title"]]
    assert len(hits) == 2
    assert all(h["reranked"] for h in hits)
    # It had more hits to choose from than were asked for (each paper's
    # passage and its details, title and abstract).
    assert len(fake_ml.reranked[-1]["passages"]) == 6


def test_on_off_and_failures(
    admin: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    library(admin, db, blobs, fake_ml)
    assert set_rerank(admin, "on") == 200
    hits, _ = search(admin, "rain")
    assert hits[0]["item_title"] == "Light rain"
    # Keyword search is not reranked (exact words, and fast).
    assert not search(admin, "rain", mode="keyword")[0][0]["reranked"]

    # A failing reranker: the usual order, no error.
    fake_ml.rerank_down = True
    hits, _ = search(admin, "rain")
    assert hits and not any(h["reranked"] for h in hits)

    assert set_rerank(admin, "off") == 200
    fake_ml.rerank_down = False
    calls = len(fake_ml.reranked)
    search(admin, "rain")
    assert len(fake_ml.reranked) == calls

    # Only rerankers the ML service offers.
    assert set_rerank(admin, "on", MODEL) == 422
    assert set_rerank(admin, "on", "nope") == 422


def test_reranker_stays_loaded_while_used(
    db: Session, settings: Settings, fake_ml: FakeML
) -> None:
    send_ml_config(db, settings, fake_ml.client())
    assert fake_ml.config["keep"] == [settings.embedding_model]
    fake_ml.device = "cuda"
    send_ml_config(db, settings, fake_ml.client())
    assert fake_ml.config["keep"] == [settings.embedding_model, "bge-reranker-v2-m3"]
