"""Figures as images (``paperus.figures``, #36): drawn from their layouts at
the scale of their page's text width, embedded by a model that takes
images, found by search through their image, reranked looking at it. The
fake ML service's images all show a crimson ring (``FakeML.PICTURE``); the
test paper's caption says nothing of the kind."""

import uuid
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paperus import figures, layouts, page_layout
from paperus.embedding import embed_file
from paperus.models import Figure, FigureEmbedding, File, PageLayouts
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.conftest import FakeML
from tests.test_page_text import paper as two_columns
from tests.test_search import add_item, upload

MULTIMODAL = "qwen3-vl-embedding-2b"


def read(admin: TestClient, db: Session, blobs: BlobStore) -> tuple[uuid.UUID, bytes]:
    """The two-column test paper, uploaded and read: its file and content."""
    file = upload(admin, add_item(admin, "Columns"), two_columns())
    file_id = uuid.UUID(file["id"])
    process_file(db, blobs, file_id)
    found = db.get(File, file_id)
    assert found is not None
    return file_id, found.blob_sha256


def use(admin: TestClient, **config: Any) -> None:  # noqa: ANN401
    current = admin.get("/api/admin/config").json()
    response = admin.put("/api/admin/config", json={**current, **config})
    assert response.status_code == 200, response.text


def test_drawn_at_the_text_widths_scale_and_embedded(
    admin: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    file_id, sha = read(admin, db, blobs)
    ml = fake_ml.client()
    assert figures.takes_images(ml, MULTIMODAL)
    assert not figures.takes_images(ml, "bge-m3")
    assert figures.missing(db, MULTIMODAL) == [sha]
    assert figures.embed(db, ml, MULTIMODAL, blobs, sha) == 1
    [figure] = db.scalars(select(Figure).where(Figure.blob_sha256 == sha))
    assert (figure.page, figure.label) == (1, "FIG. 1")
    # About 212 of 472 points of text width, which become 768 px.
    assert 330 <= figure.width <= 360
    assert figure.png.startswith(b"\x89PNG")
    assert figures.missing(db, MULTIMODAL) == []
    # Again: nothing new. Other vectors (another model's file): embedded too.
    assert figures.embed(db, ml, MULTIMODAL, blobs, sha) == 0
    fake_ml.variant = "fp16"
    assert figures.missing(db, f"{MULTIMODAL}@fp16") == [sha]
    # Layouts made anew: drawn and embedded again.
    known = db.get(PageLayouts, sha)
    assert known is not None
    layouts.store(db, sha, cast(list[page_layout.PageLayout], known.pages))
    db.commit()
    assert db.scalar(select(func.count()).select_from(FigureEmbedding)) == 0
    assert figures.missing(db, MULTIMODAL) == [sha]
    assert file_id


def test_found_by_what_it_shows(
    admin: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    file_id, sha = read(admin, db, blobs)
    ml = fake_ml.client()
    use(admin, rerank="off")
    admin.put("/api/admin/multimodal", json={"on": True})

    def first(query: str) -> dict[str, Any] | None:
        found = admin.get("/api/search", params={"q": query, "mode": "meaning"})
        assert found.status_code == 200, found.text
        hits = found.json()
        return hits[0] if hits else None

    embed_file(db, ml, MULTIMODAL, file_id)
    # A word of the text and what the figure shows: the text first, until
    # the figure has its vector.
    before = first("crimson ring Abc2")
    assert before is not None and not before["caption"]
    figures.embed(db, ml, MULTIMODAL, blobs, sha)
    hit = first("crimson ring Abc2")
    assert hit is not None
    assert (hit["caption"], hit["figure"], hit["figure_image"]) == (
        True,
        "FIG. 1",
        True,
    )


def test_reranked_looking_at_the_figure(
    admin: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    file_id, sha = read(admin, db, blobs)
    ml = fake_ml.client()
    use(admin, rerank="on")
    admin.put("/api/admin/multimodal", json={"on": True})
    embed_file(db, ml, MULTIMODAL, file_id)
    figures.embed(db, ml, MULTIMODAL, blobs, sha)
    hits = admin.get("/api/search", params={"q": "crimson ring tests"}).json()
    assert hits[0]["figure"] == "FIG. 1" and hits[0]["reranked"]
    [body] = fake_ml.reranked[-1:]
    [image] = body["images"]
    assert image["text"].startswith("FIG. 1.")


@pytest.fixture(autouse=True)
def fresh_model_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test asks the fake ML service which models take images."""
    monkeypatch.setattr(figures, "_models", (0.0, {}))


def test_fallbacks(
    admin: TestClient, db: Session, blobs: BlobStore, fake_ml: FakeML
) -> None:
    """No ML service: no images. A page without text: most of its width.
    A PDF without layouts: nothing to draw. Hits without figures: reranked
    as text."""
    fake_ml.down = True
    assert not figures.takes_images(fake_ml.client(), MULTIMODAL)
    fake_ml.down = False
    page: page_layout.PageLayout = {
        "width": 600.0,
        "height": 800.0,
        "columns": False,
        "pieces": [],
    }
    assert figures.text_width(page) == 450
    assert figures.draw(db, blobs, b"\0" * 32) == 0
    file = upload(admin, add_item(admin, "Plain"))
    process_file(db, blobs, uuid.UUID(file["id"]))
    use(admin, rerank="on")
    admin.put("/api/admin/multimodal", json={"on": True})
    admin.get("/api/search", params={"q": "drought"})
    assert "images" not in fake_ml.reranked[-1]
