"""Papers similar to a paper, among those the person can see: by their
passages' average vectors (each paper's, stored in ``paper_vectors``) and
by their details' (title and abstract), 0.7 to 0.3. On 281 papers of the
dev library, scored by papers citing each other: the first related paper
on top for 56 % (average alone: 46 %), more related ones among the ten.

A paper's average is valid while its change number is the stored one
(trash, restore, merge and moves change it); one computed before all its
passages had vectors is recomputed when they get them (``embed_file``)."""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

AVERAGE_WEIGHT = 0.7
"""The passages' average's share of the similarity; the details' the rest
(the average alone for a paper without details' vector)."""

_STALE = text(
    """
    SELECT i.id FROM items i
    WHERE i.deleted_at IS NULL
      AND (i.archived_at IS NULL OR i.id = :item)
      AND i.library_id = ANY(CAST(:libraries AS uuid[]))
      AND NOT EXISTS (
          SELECT 1 FROM paper_vectors pv
          WHERE pv.item_id = i.id AND pv.model = :model AND pv.change = i.change)
    ORDER BY i.id
    """
)

# The papers' averages (also for papers without passages: so they are not
# computed again each time), as of their current change number.
_REFRESH = text(
    """
    INSERT INTO paper_vectors (item_id, model, change, passages, embedding)
    SELECT i.id, :model, i.change, count(e.embedding), avg(e.embedding)
    FROM items i
         LEFT JOIN versions v ON v.item_id = i.id
         LEFT JOIN files f ON f.version_id = v.id AND f.deleted_at IS NULL
         LEFT JOIN file_chunks fc ON fc.file_id = f.id AND NOT fc.in_references
         LEFT JOIN embeddings e
           ON e.chunk_sha256 = fc.chunk_sha256 AND e.model = :model
    WHERE i.id = ANY(CAST(:items AS uuid[]))
    GROUP BY i.id, i.change
    ON CONFLICT (item_id, model) DO UPDATE
    SET change = excluded.change, passages = excluded.passages,
        embedding = excluded.embedding
    """
)

_SIMILAR = text(
    f"""
    WITH this AS (
        SELECT pv.embedding,
               (SELECT e.embedding FROM item_chunks ic
                JOIN embeddings e
                  ON e.chunk_sha256 = ic.chunk_sha256 AND e.model = :model
                WHERE ic.item_id = :item) AS details
        FROM paper_vectors pv
        WHERE pv.item_id = :item AND pv.model = :model
          AND pv.embedding IS NOT NULL
    ),
    others AS (
        SELECT pv.item_id, 1 - (pv.embedding <=> this.embedding) AS average,
               1 - (de.embedding <=> this.details) AS details
        FROM this, items i
             JOIN paper_vectors pv
               ON pv.item_id = i.id AND pv.model = :model
                  AND pv.embedding IS NOT NULL
             LEFT JOIN item_chunks ic ON ic.item_id = i.id
             LEFT JOIN embeddings de
               ON de.chunk_sha256 = ic.chunk_sha256 AND de.model = :model
        WHERE i.deleted_at IS NULL AND i.archived_at IS NULL AND i.id <> :item
          AND i.library_id = ANY(CAST(:libraries AS uuid[]))
    )
    SELECT item_id,
           {AVERAGE_WEIGHT} * average
           + {1 - AVERAGE_WEIGHT:.1f} * coalesce(details, average) AS similarity
    FROM others
    ORDER BY similarity DESC, item_id
    LIMIT :limit
    """
)


def refresh(db: Session, model: str, items: list[uuid.UUID]) -> None:
    """Compute these papers' averages from ``model``'s vectors, now."""
    if items:
        db.execute(_REFRESH, {"model": model, "items": sorted(items)})


def similar_items(
    db: Session,
    item_id: uuid.UUID,
    libraries: list[uuid.UUID],
    model: str,
    limit: int = 10,
) -> list[tuple[uuid.UUID, float]]:
    """The papers in ``libraries`` closest to the item, with their
    similarity (1 = the same); empty if the item has no searchable text yet.
    Papers changed since their average was computed get it anew first
    (committed)."""
    params = {"item": item_id, "libraries": libraries, "model": model}
    stale = list(db.scalars(_STALE, params))
    if stale:
        refresh(db, model, stale)
        db.commit()
    rows = db.execute(_SIMILAR, {**params, "limit": limit})
    return [(row.item_id, float(row.similarity)) for row in rows]
