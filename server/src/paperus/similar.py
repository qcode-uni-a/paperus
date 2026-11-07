"""Papers similar to a paper: the closest in meaning, by the average of
each paper's passage vectors (its reference list left out), among the
papers the person can see. Computed per request: about 0.2 s for 40,000
passages."""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

_SIMILAR = text(
    """
    WITH passages AS (
        SELECT i.id AS item_id, e.embedding
        FROM file_chunks fc
             JOIN files f ON f.id = fc.file_id
             JOIN versions v ON v.id = f.version_id
             JOIN items i ON i.id = v.item_id
             JOIN embeddings e
               ON e.chunk_sha256 = fc.chunk_sha256 AND e.model = :model
        WHERE f.deleted_at IS NULL AND i.deleted_at IS NULL
          AND NOT fc.in_references
          AND (i.archived_at IS NULL OR i.id = :item)
          AND i.library_id = ANY(CAST(:libraries AS uuid[]))
    ),
    means AS (
        SELECT item_id, avg(embedding) AS vector FROM passages GROUP BY item_id
    )
    SELECT other.item_id, 1 - (other.vector <=> this.vector) AS similarity
    FROM means other, means this
    WHERE this.item_id = :item AND other.item_id <> :item
    ORDER BY other.vector <=> this.vector
    LIMIT :limit
    """
)


def similar_items(
    db: Session,
    item_id: uuid.UUID,
    libraries: list[uuid.UUID],
    model: str,
    limit: int = 10,
) -> list[tuple[uuid.UUID, float]]:
    """The papers in ``libraries`` closest to the item, with their cosine
    similarity (1 = the same direction); empty if the item has no searchable
    text yet."""
    rows = db.execute(
        _SIMILAR,
        {
            "item": item_id,
            "libraries": libraries,
            "model": model,
            "limit": limit,
        },
    )
    return [(row.item_id, float(row.similarity)) for row in rows]
