"""Search: by keyword, by meaning, or both (hybrid, the default)."""

import logging
import time
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from paperus import library, metrics
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.config import Settings
from paperus.ml import MLClient, MLRejected, MLUnavailable
from paperus.models import Item
from paperus.system import SystemConfig, load_config

log = logging.getLogger(__name__)
router = APIRouter(tags=["search"])

Mode = Literal["hybrid", "keyword", "meaning"]
Match = Literal["keyword", "meaning"]

# Candidates per method before fusing; reciprocal rank fusion constant.
CANDIDATES = 50
RRF_K = 60
QUERY_TIMEOUT = 30.0
# Hits the reranker reorders (then cut to what was asked), and how long a
# search waits for it before showing them in the usual order.
RERANK_POOL = 40
RERANK_TIMEOUT = 15.0


class Passage(BaseModel):
    passage_id: str
    """``<file id>#<position>`` (or the note's id for notes): stable while the
    text is unchanged."""
    kind: Literal["paper", "note"] = "paper"
    """From a paper's file, or from a note."""
    item_id: uuid.UUID | None
    """The paper (not for notes)."""
    item_title: str
    """The paper's title, or the note's."""
    item_authors: list[str] = []
    """The paper's authors ("Family, Given"); empty for notes."""
    item_year: int | None = None
    """The paper's year of publication."""
    version_id: uuid.UUID | None
    file_id: uuid.UUID | None
    note_id: uuid.UUID | None = None
    position: int
    page: int | None
    snippet: str
    """HTML: the passage's text escaped, keyword matches wrapped in ``<mark>``."""
    score: float
    matched: list[Match]
    """How the passage was found: by its words, its meaning, or both."""
    in_references: bool
    """From the item's reference list (found by words only)."""
    reranked: bool = False
    """Ordered by the reranker (``score`` is then its score)."""


# Keyword and meaning candidates are ranked separately, then fused by
# reciprocal rank (scores of the two methods are not comparable). Text is
# HTML-escaped before ts_headline adds <mark>, so snippets are safe as HTML.
_SEARCH = text(
    f"""
    WITH q AS (SELECT websearch_to_tsquery('simple', :query) AS tsq),
    visible AS NOT MATERIALIZED (
        SELECT 'paper' AS kind, fc.file_id AS source_id, fc.position, fc.page,
               fc.chunk_sha256, fc.in_references, f.version_id,
               i.id AS item_id, i.title AS item_title
        FROM file_chunks fc
             JOIN files f ON f.id = fc.file_id
             JOIN versions v ON v.id = f.version_id
             JOIN items i ON i.id = v.item_id
        WHERE f.deleted_at IS NULL AND i.deleted_at IS NULL
          -- The archive only if asked for (or within one of its papers).
          AND (i.archived_at IS NULL OR :archived OR CAST(:item AS uuid) IS NOT NULL)
          -- Only libraries the person can read.
          AND i.library_id = ANY(CAST(:libraries AS uuid[]))
          AND (cardinality(CAST(:types AS text[])) = 0
               OR i.type = ANY(CAST(:types AS text[])))
          -- Within one paper only, if asked.
          AND (CAST(:item AS uuid) IS NULL OR i.id = CAST(:item AS uuid))
        UNION ALL
        SELECT 'note', nc.note_id, nc.position, NULL, nc.chunk_sha256, false,
               NULL, NULL, n.title
        FROM note_chunks nc JOIN notes n ON n.id = nc.note_id
        WHERE n.deleted_at IS NULL
          AND n.library_id = ANY(CAST(:libraries AS uuid[]))
          AND (cardinality(CAST(:types AS text[])) = 0
               OR 'note' = ANY(CAST(:types AS text[])))
          AND CAST(:item AS uuid) IS NULL
    ),
    keyword AS (
        SELECT vis.source_id, vis.position, row_number() OVER (
                   ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC, vis.source_id, vis.position
               ) AS rank
        FROM visible vis JOIN chunks c ON c.sha256 = vis.chunk_sha256, q
        WHERE :use_keyword AND c.tsv @@ q.tsq
        ORDER BY rank LIMIT :candidates
    ),
    meaning AS (
        SELECT vis.source_id, vis.position, row_number() OVER (
                   ORDER BY e.embedding <=> CAST(:vector AS halfvec),
                            vis.source_id, vis.position
               ) AS rank
        FROM visible vis
             JOIN embeddings e
               ON e.chunk_sha256 = vis.chunk_sha256 AND e.model = :model
        WHERE :use_meaning AND NOT vis.in_references
        ORDER BY rank LIMIT :candidates
    ),
    fused AS (
        SELECT source_id, position, sum(1.0 / ({RRF_K} + rank)) AS score,
               bool_or(source = 'keyword') AS by_keyword,
               bool_or(source = 'meaning') AS by_meaning
        FROM (
            SELECT source_id, position, rank, 'keyword' AS source FROM keyword
            UNION ALL
            SELECT source_id, position, rank, 'meaning' AS source FROM meaning
        ) AS candidates
        GROUP BY source_id, position
    ),
    -- The best few per paper (or note), so one paper cannot fill the list.
    capped AS (
        SELECT fused.*, row_number() OVER (
                   PARTITION BY coalesce(vis.item_id, vis.source_id)
                   ORDER BY fused.score DESC, source_id, position
               ) AS nth
        FROM fused JOIN visible vis USING (source_id, position)
    )
    SELECT vis.kind, vis.source_id, vis.position, vis.page, vis.in_references,
           c.text AS chunk_text,
           vis.version_id,
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
    FROM capped fused
         JOIN visible vis USING (source_id, position)
         JOIN chunks c ON c.sha256 = vis.chunk_sha256,
         q
    WHERE fused.nth <= :per_item
    ORDER BY fused.score DESC, vis.source_id, vis.position
    LIMIT :limit
    """
)


def _query_vector(ml: MLClient, model: str, query: str) -> tuple[str, str] | None:
    """The query's vector as pgvector text, and what the passages' vectors
    to compare with are stored as; None if the ML service is down."""
    try:
        embedded = ml.embed_named(
            [query], model=model, kind="query", timeout=QUERY_TIMEOUT
        )
    except (MLUnavailable, MLRejected) as error:
        log.warning("search by meaning unavailable, keyword search only: %s", error)
        return None
    [vector] = embedded.values
    return "[" + ",".join(f"{x:.6g}" for x in vector) + "]", embedded.vectors


def run_search(
    db: Session,
    access: Access,
    ml: MLClient,
    settings: Settings,
    q: str,
    *,
    limit: int = 20,
    mode: Mode = "hybrid",
    types: list[str] | None = None,
    library_id: uuid.UUID | None = None,
    per_item: int | None = None,
    item_id: uuid.UUID | None = None,
    rerank: bool | None = None,
    archived: bool = False,
) -> tuple[Mode, list[Passage]]:
    """Passages for ``q`` that the person may read, and the mode used
    (hybrid falls back to keywords without the ML service). ``per_item``:
    at most that many per paper or note (more candidates are looked at, so
    more papers fill the list); ``item_id``: within that paper only;
    ``archived``: archived papers too;
    ``rerank``: overrides the administration's setting (for evaluating)."""
    started = time.perf_counter()
    config = load_config(db, settings)
    model = config.embedding_model
    vector = None
    if mode != "keyword" and (found := _query_vector(ml, model, q)) is not None:
        vector, model = found
    used: Mode = mode if vector is not None or mode == "keyword" else "keyword"
    reranker = _reranker(config, ml) if used != "keyword" else None
    if rerank is not None:
        reranker = config.rerank_model if rerank and used != "keyword" else None
    asked, per_paper = limit, per_item
    if reranker:
        # More hits, and more per paper, for the reranker to choose from.
        limit = max(limit, RERANK_POOL)
        per_item = per_item + 1 if per_item else None
    libraries = access.readable
    if library_id is not None:
        libraries = [library_id] if access.can_read(library_id) else []
    rows = (
        db.execute(
            _SEARCH,
            {
                "query": q,
                "limit": limit,
                "vector": vector,
                "model": model,
                "use_keyword": used != "meaning",
                "use_meaning": vector is not None,
                "types": types or [],
                "libraries": libraries,
                "item": item_id,
                "archived": archived,
                "per_item": per_item or limit,
                "candidates": CANDIDATES * 4 if per_item else CANDIDATES,
            },
        )
        .mappings()
        .all()
    )
    passages = [
        Passage(
            passage_id=f"{row['source_id']}#{row['position']}",
            kind=row["kind"],
            item_id=row["item_id"],
            item_title=row["item_title"],
            version_id=row["version_id"],
            file_id=row["source_id"] if row["kind"] == "paper" else None,
            note_id=row["source_id"] if row["kind"] == "note" else None,
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
    texts = [row["chunk_text"] for row in rows]
    if reranker and passages:
        passages = _rerank(ml, reranker, q, passages, texts, per_paper)
    passages = passages[:asked]
    _add_authors(db, passages)
    metrics.SEARCHES.labels(used).inc()
    metrics.SEARCH_SECONDS.observe(time.perf_counter() - started)
    return used, passages


def _reranker(config: SystemConfig, ml: MLClient) -> str | None:
    """The reranker to use, if any: "auto" uses it when the ML service runs
    on a GPU (on a CPU a search would take seconds)."""
    if config.rerank == "off":
        return None
    if config.rerank == "on":
        return config.rerank_model
    try:
        return config.rerank_model if ml.device() == "cuda" else None
    except (MLUnavailable, MLRejected):
        return None


def _rerank(
    ml: MLClient,
    model: str,
    query: str,
    passages: list[Passage],
    texts: list[str],
    per_item: int | None,
) -> list[Passage]:
    """The hits in the reranker's order, at most ``per_item`` per paper or
    note; in the usual order if the reranker fails or takes too long."""
    started = time.perf_counter()
    try:
        scores = ml.rerank(query, texts, model=model, timeout=RERANK_TIMEOUT)
    except (MLUnavailable, MLRejected) as error:
        log.warning("reranking unavailable, usual order: %s", error)
        return passages
    metrics.ML_SECONDS.labels("rerank").observe(time.perf_counter() - started)
    for passage, score in zip(passages, scores, strict=True):
        passage.score = score
        passage.reranked = True
    ordered = sorted(passages, key=lambda p: p.score, reverse=True)
    if per_item is None:
        return ordered
    taken: dict[uuid.UUID | None, int] = {}
    result = []
    for passage in ordered:
        source = passage.item_id or passage.note_id
        if taken.get(source, 0) < per_item:
            taken[source] = taken.get(source, 0) + 1
            result.append(passage)
    return result


def _add_authors(db: Session, passages: list[Passage]) -> None:
    """Authors and year, by which people recognise a paper (one query for
    all papers in the results)."""
    ids = {p.item_id for p in passages if p.item_id is not None}
    if not ids:
        return
    found = {}
    for item in db.scalars(select(Item).where(Item.id.in_(ids))):
        csl = library.citation_csl(item)
        found[item.id] = (library.author_names(csl), library.issued_year(csl))
    for passage in passages:
        known = found.get(passage.item_id) if passage.item_id else None
        if known is not None:
            passage.item_authors, passage.item_year = known


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
    per_item: Annotated[int | None, Query(ge=1, le=100)] = None,
    item: uuid.UUID | None = None,
    archived: bool = False,
) -> list[Passage]:
    """Passages for ``q`` in the libraries the person can read (or one
    ``library``): its words (quotes for phrases, ``-`` to exclude), its
    meaning, or both; ``type`` (repeatable, CSL types) limits the items.
    ``per_item`` keeps the best few per paper or note, so more papers fit;
    ``item`` searches within one paper; ``archived=true`` includes the
    archive. The ``X-Search-Mode`` header says
    what was used: without the ML service, hybrid search falls back to
    keywords."""
    used, passages = run_search(
        db,
        access,
        request.app.state.ml,
        request.app.state.settings,
        q,
        limit=limit,
        mode=mode,
        types=type,
        library_id=library_id,
        per_item=per_item,
        item_id=item,
        archived=archived,
    )
    response.headers["X-Search-Mode"] = used
    return passages
