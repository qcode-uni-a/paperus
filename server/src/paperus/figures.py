"""Figures as images for multimodal search (#36): each captioned figure of a
PDF's layout (``page_layout``: its box and its caption's label) drawn once,
at a scale set by its page's text width, and embedded by an embedding model
that takes images, in the same space as the passages. Search finds a
caption's passage by the better of its text's vector and its figure's
(``api.search``); the reranker looks at the drawn figure with its caption."""

import logging
import time
from typing import cast

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from paperus import page_layout, pdf
from paperus.ml import MLClient, MLRejected, MLUnavailable
from paperus.models import Figure, FigureEmbedding, PageLayouts
from paperus.storage import BlobStore

log = logging.getLogger(__name__)

TEXT_WIDTH_PX = 768
"""How many pixels a page's text width becomes: a figure across both
columns about this wide, one in a column about half; their labels the same
size either way."""
BATCH = 8
MODELS_FOR = 300.0
"""Seconds the ML service's list of models is trusted."""

_models: tuple[float, dict[str, bool]] = (0.0, {})


def takes_images(ml: MLClient, model: str) -> bool:
    """Whether the ML service's ``model`` takes images (multimodal search);
    False if the service cannot say."""
    global _models  # a small cache of the service's list
    at, known = _models
    if time.monotonic() - at > MODELS_FOR or model not in known:
        try:
            known = {m["name"]: bool(m.get("images")) for m in ml.models()}
        except (MLUnavailable, MLRejected):
            return False
        _models = (time.monotonic(), known)
    return known.get(model, False)


def text_width(page: page_layout.PageLayout) -> float:
    """The page's text width (points): from its pieces' leftmost edge to
    their rightmost (both columns), else most of the page."""
    pieces = page["pieces"]
    if not pieces:
        return page["width"] * 0.75
    return float(max(p["x"] + p["width"] for p in pieces) - min(p["x"] for p in pieces))


def wanted(
    pages: list[page_layout.PageLayout],
) -> list[tuple[int, str, page_layout.Figure, float]]:
    """The captioned figures of a PDF's layouts: page (from 1), label, box,
    and the scale to draw it at (pixels per point)."""
    found = {}
    for number, page in enumerate(pages, 1):
        scale = TEXT_WIDTH_PX / max(text_width(page), 1.0)
        for figure in page.get("figures", []):
            label = figure.get("caption")
            if label and (number, label) not in found:
                found[(number, label)] = (number, label, figure, scale)
    return list(found.values())


def forget(db: Session, sha256: bytes) -> None:
    """A PDF's figures dropped (its layouts were made anew: boxes may have
    moved); drawn and embedded again by the sweep."""
    db.execute(delete(Figure).where(Figure.blob_sha256 == sha256))


def draw(db: Session, blobs: BlobStore, sha256: bytes) -> int:
    """Draw the PDF's captioned figures not drawn yet; how many."""
    layouts = db.get(PageLayouts, sha256)
    if layouts is None or layouts.version != page_layout.VERSION:
        return 0
    drawn = {
        (page, label)
        for page, label in db.execute(
            select(Figure.page, Figure.label).where(Figure.blob_sha256 == sha256)
        )
    }
    pages = cast(list[page_layout.PageLayout], layouts.pages)
    todo = [w for w in wanted(pages) if (w[0], w[1]) not in drawn]
    if not todo:
        return 0
    with blobs.local_file(sha256) as path:
        for number, label, box, scale in todo:
            image = pdf.figure(path, number - 1, box, scale)
            width, height = _png_size(image)
            db.execute(
                insert(Figure)
                .values(
                    blob_sha256=sha256,
                    page=number,
                    label=label,
                    width=width,
                    height=height,
                    png=image,
                )
                .on_conflict_do_nothing()
            )
    db.commit()
    return len(todo)


def _png_size(image: bytes) -> tuple[int, int]:
    return int.from_bytes(image[16:20], "big"), int.from_bytes(image[20:24], "big")


def embed(
    db: Session, ml: MLClient, model: str, blobs: BlobStore, sha256: bytes
) -> int:
    """Draw the PDF's figures if needed and embed those without a vector
    from ``model``'s current file; how many were embedded."""
    draw(db, blobs, sha256)
    vectors = ml.vectors_name(model)
    has_vector = select(FigureEmbedding.page, FigureEmbedding.label).where(
        FigureEmbedding.blob_sha256 == sha256, FigureEmbedding.model == vectors
    )
    figures = list(
        db.scalars(
            select(Figure)
            .where(
                Figure.blob_sha256 == sha256,
                func.row(Figure.page, Figure.label).not_in(has_vector),
            )
            .order_by(Figure.page, Figure.label)
        )
    )
    for start in range(0, len(figures), BATCH):
        batch = figures[start : start + BATCH]
        embedded = ml.embed_images([f.png for f in batch], model=model)
        db.execute(
            insert(FigureEmbedding)
            .values(
                [
                    {
                        "blob_sha256": f.blob_sha256,
                        "page": f.page,
                        "label": f.label,
                        "model": embedded.vectors,
                        "embedding": v,
                    }
                    for f, v in zip(batch, embedded.values, strict=True)
                ]
            )
            .on_conflict_do_nothing()
        )
        db.commit()
    return len(figures)


# PDFs (outside the trash, read, their layouts current) with captioned
# figures that have no vector from the model yet: fewer vectors than the
# layouts have captioned figures (drawn or not).
_MISSING = text(
    """
    SELECT pl.blob_sha256
    FROM page_layouts pl
    WHERE pl.version = :version
      AND EXISTS (
          SELECT 1 FROM files f
          WHERE f.blob_sha256 = pl.blob_sha256 AND f.deleted_at IS NULL
            AND f.text_status = 'done')
      AND (SELECT count(DISTINCT (p.n, fig->>'caption'))
           FROM jsonb_array_elements(pl.pages) WITH ORDINALITY AS p(page, n),
                jsonb_array_elements(coalesce(p.page->'figures', '[]')) AS fig
           WHERE fig ? 'caption')
          > (SELECT count(*) FROM figure_embeddings fe
             WHERE fe.blob_sha256 = pl.blob_sha256 AND fe.model = :vectors)
    ORDER BY pl.created_at DESC
    LIMIT :limit
    """
)


def missing(db: Session, vectors: str, limit: int = 200) -> list[bytes]:
    """PDFs whose captioned figures lack vectors stored as ``vectors``."""
    return list(
        db.scalars(
            _MISSING,
            {"version": page_layout.VERSION, "vectors": vectors, "limit": limit},
        )
    )
