"""Search: by keyword, by meaning, or both (hybrid, the default)."""

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from paperus.api.deps import DB, CurrentAccess
from paperus.ml import MLClient, MLUnavailable
from paperus.system import load_config

log = logging.getLogger(__name__)
router = APIRouter(tags=["search"])

Mode = Literal["hybrid", "keyword", "meaning"]
Match = Literal["keyword", "meaning"]

# Candidates per method before fusing; reciprocal rank fusion constant.
CANDIDATES = 50
RRF_K = 60
QUERY_TIMEOUT = 30.0


class Passage(BaseModel):
    passage_id: str
    """``<file id>#<position>``: stable while the file's text is unchanged."""
    item_id: uuid.UUID
    item_title: str
    version_id: uuid.UUID
    file_id: uuid.UUID
    position: int
    page: int | None
    snippet: str
    """HTML: the passage's text escaped, keyword matches wrapped in ``<mark>``."""
    score: float
    matched: list[Match]
    """How the passage was found: by its words, its meaning, or both."""
    in_references: bool
    """From the item's reference list (found by words only)."""


# Keyword and meaning candidates are ranked separately, then fused by
# reciprocal rank (scores of the two methods are not comparable). Text is
# HTML-escaped before ts_headline adds <mark>, so snippets are safe as HTML.
_SEARCH = text(
    f"""
    WITH q AS (SELECT websearch_to_tsquery('simple', :query) AS tsq),
    visible AS NOT MATERIALIZED (
        SELECT fc.file_id, fc.position, fc.page, fc.chunk_sha256, fc.in_references,
               f.version_id,
               i.id AS item_id, i.title AS item_title
        FROM file_chunks fc
             JOIN files f ON f.id = fc.file_id
             JOIN versions v ON v.id = f.version_id
             JOIN items i ON i.id = v.item_id
        WHERE f.deleted_at IS NULL AND i.deleted_at IS NULL
          -- Only libraries the person can read.
          AND i.library_id = ANY(CAST(:libraries AS uuid[]))
          AND (cardinality(CAST(:types AS text[])) = 0
               OR i.type = ANY(CAST(:types AS text[])))
    ),
    keyword AS (
        SELECT vis.file_id, vis.position, row_number() OVER (
                   ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC, vis.file_id, vis.position
               ) AS rank
        FROM visible vis JOIN chunks c ON c.sha256 = vis.chunk_sha256, q
        WHERE :use_keyword AND c.tsv @@ q.tsq
        ORDER BY rank LIMIT {CANDIDATES}
    ),
    meaning AS (
        SELECT vis.file_id, vis.position, row_number() OVER (
                   ORDER BY e.embedding <=> CAST(:vector AS halfvec),
                            vis.file_id, vis.position
               ) AS rank
        FROM visible vis
             JOIN embeddings e
               ON e.chunk_sha256 = vis.chunk_sha256 AND e.model = :model
        WHERE :use_meaning AND NOT vis.in_references
        ORDER BY rank LIMIT {CANDIDATES}
    ),
    fused AS (
        SELECT file_id, position, sum(1.0 / ({RRF_K} + rank)) AS score,
               bool_or(source = 'keyword') AS by_keyword,
               bool_or(source = 'meaning') AS by_meaning
        FROM (
            SELECT file_id, position, rank, 'keyword' AS source FROM keyword
            UNION ALL
            SELECT file_id, position, rank, 'meaning' AS source FROM meaning
        ) AS candidates
        GROUP BY file_id, position
    )
    SELECT vis.file_id, vis.position, vis.page, vis.in_references, vis.version_id,
           vis.item_id,
           vis.item_title, fused.score, fused.by_keyword, fused.by_meaning,
           CASE WHEN fused.by_keyword THEN ts_headline(
               'simple',
               replace(replace(replace(c.text, '&', '&amp;'), '<', '&lt;'),
                       '>', '&gt;'),
               q.tsq,
               'StartSel=<mark>, StopSel=</mark>, MaxWords=40, MinWords=15,'
               ' MaxFragments=2, FragmentDelimiter=" … "'
           )
           -- Found by meaning only: no words to mark, so the passage's start.
           ELSE replace(replace(replace(
               CASE WHEN length(c.text) > 320
                    THEN left(c.text, 320) || '…' ELSE c.text END,
               '&', '&amp;'), '<', '&lt;'), '>', '&gt;')
           END AS snippet
    FROM fused
         JOIN visible vis USING (file_id, position)
         JOIN chunks c ON c.sha256 = vis.chunk_sha256,
         q
    ORDER BY fused.score DESC, vis.file_id, vis.position
    LIMIT :limit
    """
)


def _query_vector(ml: MLClient, model: str, query: str) -> str | None:
    """The query's vector as pgvector text, or None if the ML service is down."""
    try:
        [vector] = ml.embed([query], model=model, kind="query", timeout=QUERY_TIMEOUT)
    except MLUnavailable:
        log.warning("search by meaning unavailable; keyword search only", exc_info=True)
        return None
    return "[" + ",".join(f"{x:.6g}" for x in vector) + "]"


@router.get("/api/search")
def search(
    request: Request,
    response: Response,
    db: DB,
    access: CurrentAccess,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    mode: Mode = "hybrid",
    type: Annotated[list[str] | None, Query()] = None,
    library_id: Annotated[uuid.UUID | None, Query(alias="library")] = None,
) -> list[Passage]:
    """Passages for ``q`` in the libraries the person can read (or one
    ``library``): its words (quotes for phrases, ``-`` to exclude), its
    meaning, or both; ``type`` (repeatable, CSL types) limits the items. The
    ``X-Search-Mode`` header says what was used: without the ML service,
    hybrid search falls back to keywords."""
    model = load_config(db, request.app.state.settings).embedding_model
    vector = None
    if mode != "keyword":
        vector = _query_vector(request.app.state.ml, model, q)
    used: Mode = mode if vector is not None or mode == "keyword" else "keyword"
    response.headers["X-Search-Mode"] = used
    libraries = access.readable
    if library_id is not None:
        libraries = [library_id] if access.can_read(library_id) else []
    rows = db.execute(
        _SEARCH,
        {
            "query": q,
            "limit": limit,
            "vector": vector,
            "model": model,
            "use_keyword": used != "meaning",
            "use_meaning": vector is not None,
            "types": type or [],
            "libraries": libraries,
        },
    ).mappings()
    return [
        Passage(
            passage_id=f"{row['file_id']}#{row['position']}",
            item_id=row["item_id"],
            item_title=row["item_title"],
            version_id=row["version_id"],
            file_id=row["file_id"],
            position=row["position"],
            page=row["page"],
            snippet=row["snippet"],
            score=float(row["score"]),
            in_references=row["in_references"],
            matched=[
                m
                for m, hit in (
                    ("keyword", row["by_keyword"]),
                    ("meaning", row["by_meaning"]),
                )
                if hit
            ],
        )
        for row in rows
    ]
