"""Search: by keyword, by meaning, or both (hybrid, the default)."""

import logging
import time
import uuid
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select, text, tuple_
from sqlalchemy.orm import Session

from paperus import figures, library, metrics, page_layout
from paperus.access import Access
from paperus.api.deps import DB, CurrentAccess
from paperus.config import Settings
from paperus.ml import MLClient, MLRejected, MLUnavailable
from paperus.models import Figure, File, Item, PageLayouts
from paperus.system import SystemConfig, load_config

log = logging.getLogger(__name__)
router = APIRouter(tags=["search"])

Mode = Literal["hybrid", "keyword", "meaning"]
Match = Literal["keyword", "meaning"]

# Candidates per method before fusing; reciprocal rank fusion constant.
CANDIDATES = 50
RRF_K = 60
QUERY_TIMEOUT = 30.0
RERANK_BUDGET = 0.5
"""Seconds a search gives the reranker: it reorders as many of the best hits
as it reads in that time at its speed measured so far (``rerank_pool``),
the others follow in the usual order. Qwen3-VL-Reranker on an RTX 2080
takes 60-80 ms a passage, about 60 ms a figure; a small reranker a quarter
of that. Measured on 200 questions: the right paper first 0.90 without
reranking, 0.94 reranking 5 hits, 0.96 reranking 10 or 20, no better
with 40."""
RERANK_FEWEST = 5
RERANK_MOST = 20
RERANK_TIMEOUT = 15.0
"""How long a search waits for the reranker before showing the hits in the
usual order."""

_seconds_each: dict[str, float] = {}
"""The rerankers' measured seconds per hit (a moving average), by model."""
# A match in a paper's title or abstract (its details) counts this much more
# than one in a passage of some text.
DETAILS_WEIGHT = 2.0


class Passage(BaseModel):
    passage_id: str
    """``<file id>#<position>`` (or the note's id for notes; ``<paper
    id>#details`` for a paper's details): stable while the text is
    unchanged."""
    kind: Literal["paper", "note", "details"] = "paper"
    """From a paper's file, from a note, or a paper's details (its title and
    abstract)."""
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
    caption: bool = False
    """A figure's or table's caption."""
    figure: str | None = None
    """For a caption: what it labels, as the paper writes it ("FIG. 3",
    "Table I")."""
    figure_image: bool = False
    """Its figure was found on the page: drawn at
    ``/api/files/{file_id}/figure?page=…&label=…``."""
    figure_top: int | None = None
    figure_left: int | None = None
    """Where it begins on its page (points from the top left): its link
    opens the paper there."""
    figure_width: int | None = None
    figure_height: int | None = None
    """Its size on the page (points): upright ones are shown beside their
    caption, wide ones above it."""
    reranked: bool = False
    """Ordered by the reranker (``score`` is then its score)."""


# The passages the person may read (papers' passages, notes', papers'
# details), narrowed by ``{papers}``, ``{notes}`` and ``{details}``: all of
# them, or only some (by index, without going through all).
_VISIBLE = """
        SELECT 'paper' AS kind, fc.file_id AS source_id, fc.position, fc.page,
               fc.chunk_sha256, fc.in_references, f.version_id,
               i.id AS item_id, i.title AS item_title, fc.caption,
               f.blob_sha256, fc.figure
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
          -- Figures (their captions) only, if asked.
          AND (NOT :figures OR fc.caption)
          AND {papers}
        UNION ALL
        SELECT 'note', nc.note_id, nc.position, NULL, nc.chunk_sha256, false,
               NULL, NULL, n.title, false, NULL, NULL
        FROM note_chunks nc JOIN notes n ON n.id = nc.note_id
        WHERE n.deleted_at IS NULL
          AND n.library_id = ANY(CAST(:libraries AS uuid[]))
          AND (cardinality(CAST(:types AS text[])) = 0
               OR 'note' = ANY(CAST(:types AS text[])))
          AND CAST(:item AS uuid) IS NULL
          AND NOT :figures
          AND {notes}
        UNION ALL
        -- A paper's details: its title and abstract, with or without a file.
        SELECT 'details', i.id, 0, NULL, ic.chunk_sha256, false,
               NULL, i.id, i.title, false, NULL, NULL
        FROM item_chunks ic JOIN items i ON i.id = ic.item_id
        WHERE i.deleted_at IS NULL
          AND (i.archived_at IS NULL OR :archived OR CAST(:item AS uuid) IS NOT NULL)
          AND i.library_id = ANY(CAST(:libraries AS uuid[]))
          AND (cardinality(CAST(:types AS text[])) = 0
               OR i.type = ANY(CAST(:types AS text[])))
          AND (CAST(:item AS uuid) IS NULL OR i.id = CAST(:item AS uuid))
          AND NOT :figures
          AND {details}
"""
_ALL = _VISIBLE.format(papers="true", notes="true", details="true")
_NEAR = _VISIBLE.format(
    papers="(fc.chunk_sha256 IN (SELECT chunk_sha256 FROM near)"
    " OR (f.blob_sha256, fc.page, fc.figure)"
    " IN (SELECT blob_sha256, page, label FROM near_figures))",
    notes="nc.chunk_sha256 IN (SELECT chunk_sha256 FROM near)",
    details="ic.chunk_sha256 IN (SELECT chunk_sha256 FROM near)",
)
_HITS = _VISIBLE.format(
    papers="(fc.file_id, fc.position) IN (SELECT source_id, position FROM fused)",
    notes="(nc.note_id, nc.position) IN (SELECT source_id, position FROM fused)",
    details="(i.id, 0) IN (SELECT source_id, position FROM fused)",
)
NEAREST = 1000
"""Search by meaning compares with the nearest so many passages' vectors
(and figures') of all first, then keeps those the person may read: the same
hits as comparing with every passage they may read, as long as enough of
them are among those (else it does that)."""

# Keyword and meaning candidates are ranked separately, then fused by
# reciprocal rank (scores of the two methods are not comparable). Text is
# HTML-escaped before ts_headline adds <mark>, so snippets are safe as HTML.
_SEARCH = text(
    f"""
    WITH q AS (SELECT websearch_to_tsquery('simple', :query) AS tsq),
    visible AS NOT MATERIALIZED ({_ALL}    ),
    keyword AS (
        SELECT vis.source_id, vis.position, vis.kind, row_number() OVER (
                   ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC, vis.source_id, vis.position
               ) AS rank
        FROM visible vis JOIN chunks c ON c.sha256 = vis.chunk_sha256, q
        WHERE :use_keyword AND c.tsv @@ q.tsq
        ORDER BY rank LIMIT :candidates
    ),
    near AS MATERIALIZED (
        SELECT chunk_sha256, embedding <=> CAST(:vector AS halfvec) AS distance
        FROM embeddings
        WHERE :use_meaning AND model = :model
        ORDER BY distance LIMIT :nearest
    ),
    near_figures AS MATERIALIZED (
        SELECT blob_sha256, page, label,
               embedding <=> CAST(:vector AS halfvec) AS distance
        FROM figure_embeddings
        WHERE :use_meaning AND model = :model
        ORDER BY distance LIMIT :nearest
    ),
    by_nearest AS MATERIALIZED (
        SELECT vis.source_id, vis.position, vis.kind,
               n.distance IS NOT NULL AS near_text,
               least(coalesce(n.distance, 2), coalesce(nf.distance, 2)) AS distance
        FROM ({_NEAR}) AS vis
             LEFT JOIN near n ON n.chunk_sha256 = vis.chunk_sha256
             LEFT JOIN near_figures nf
               ON nf.blob_sha256 = vis.blob_sha256 AND nf.page = vis.page
                  AND nf.label = vis.figure
        WHERE NOT vis.in_references
    ),
    -- The nearest suffice if enough of them may be read (or they are all).
    enough AS MATERIALIZED (
        SELECT (SELECT count(*) FROM by_nearest WHERE near_text) >= :candidates
               OR (SELECT count(*) FROM near) < :nearest AS yes
    ),
    meaning AS (
        -- A caption by the better of its text's vector and its figure's
        -- (a model that takes images: multimodal search).
        SELECT source_id, position, kind, row_number() OVER (
                   ORDER BY distance, source_id, position
               ) AS rank
        FROM (
            SELECT source_id, position, kind, distance
            FROM by_nearest
            WHERE (SELECT yes FROM enough)
            UNION ALL
            SELECT vis.source_id, vis.position, vis.kind, least(
                       e.embedding <=> CAST(:vector AS halfvec),
                       coalesce(fe.embedding <=> CAST(:vector AS halfvec), 2))
            FROM visible vis
                 JOIN embeddings e
                   ON e.chunk_sha256 = vis.chunk_sha256 AND e.model = :model
                 LEFT JOIN figure_embeddings fe
                   ON fe.blob_sha256 = vis.blob_sha256 AND fe.page = vis.page
                      AND fe.label = vis.figure AND fe.model = :model
            WHERE :use_meaning AND NOT vis.in_references
              AND NOT (SELECT yes FROM enough)
        ) AS compared
        ORDER BY rank LIMIT :candidates
    ),
    fused AS (
        SELECT source_id, position,
               sum(CASE WHEN kind = 'details' AND source = 'keyword'
                        THEN {DETAILS_WEIGHT} ELSE 1.0 END
                   / ({RRF_K} + rank)) AS score,
               bool_or(source = 'keyword') AS by_keyword,
               bool_or(source = 'meaning') AS by_meaning
        FROM (
            SELECT source_id, position, kind, rank, 'keyword' AS source FROM keyword
            UNION ALL
            SELECT source_id, position, kind, rank, 'meaning' AS source FROM meaning
        ) AS candidates
        GROUP BY source_id, position
    ),
    visible_hits AS MATERIALIZED ({_HITS}    ),
    -- The best few per paper (or note), so one paper cannot fill the list.
    capped AS (
        SELECT fused.*, row_number() OVER (
                   PARTITION BY coalesce(vis.item_id, vis.source_id)
                   ORDER BY fused.score DESC, source_id, position
               ) AS nth
        FROM fused JOIN visible_hits vis USING (source_id, position)
    )
    SELECT vis.kind, vis.source_id, vis.position, vis.page, vis.in_references,
           vis.caption, vis.blob_sha256, vis.figure AS figure_label,
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
         JOIN visible_hits vis USING (source_id, position)
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
    figures: bool = False,
) -> tuple[Mode, list[Passage]]:
    """Passages for ``q`` that the person may read, and the mode used
    (hybrid falls back to keywords without the ML service). ``per_item``:
    at most that many per paper or note (more candidates are looked at, so
    more papers fill the list); ``item_id``: within that paper only;
    ``archived``: archived papers too; ``figures``: figures' and tables'
    captions only;
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
    pool = rerank_pool(reranker) if reranker else 0
    if reranker:
        # More hits, and more per paper, for the reranker to choose from.
        limit = max(limit, pool)
        per_item = per_item + 1 if per_item else None
    libraries = access.readable
    if library_id is not None:
        libraries = [library_id] if access.can_read(library_id) else []
    # A plan for these parameters each time: psycopg prepares the query
    # after a few runs, and PostgreSQL's generic plan for it (not knowing
    # the vector, the filters) took 0.47 s instead of 0.06 s.
    db.execute(text("SET LOCAL plan_cache_mode = force_custom_plan"))
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
                "figures": figures,
                "per_item": per_item or limit,
                "candidates": CANDIDATES * 4 if per_item else CANDIDATES,
                # Narrow searches compare with every passage at once.
                "nearest": 0 if figures or item_id else NEAREST,
            },
        )
        .mappings()
        .all()
    )
    passages = [
        Passage(
            passage_id=f"{row['source_id']}#"
            + ("details" if row["kind"] == "details" else str(row["position"])),
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
            caption=row["caption"],
            figure=page_layout.figure_label(row["chunk_text"])
            if row["caption"]
            else None,
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
        drawn = _figures_to_rerank(db, ml, reranker, rows[:pool])
        reranked = _rerank(ml, reranker, q, passages[:pool], texts, drawn)
        passages = _per_item(reranked + passages[pool:], per_paper)
    passages = passages[:asked]
    _add_authors(db, passages)
    _add_figures(db, passages)
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


def rerank_pool(model: str) -> int:
    """How many of the best hits ``model`` reranks: as many as it reads in
    ``RERANK_BUDGET`` at its measured speed (``RERANK_FEWEST`` until
    measured)."""
    each = _seconds_each.get(model)
    if each is None:
        return RERANK_FEWEST
    return max(RERANK_FEWEST, min(RERANK_MOST, int(RERANK_BUDGET / max(each, 1e-6))))


def _measured(model: str, seconds: float, hits: int) -> None:
    each = seconds / hits
    known = _seconds_each.get(model)
    _seconds_each[model] = each if known is None else 0.7 * known + 0.3 * each


def _figures_to_rerank(
    db: Session, ml: MLClient, reranker: str, rows: Sequence[Any]
) -> dict[int, tuple[bytes, str]]:
    """For a reranker that takes images: the captions' figures (by their
    place in ``rows``), drawn, with the caption's text."""
    if not figures.takes_images(ml, reranker):
        return {}
    wanted = [
        (n, (row["blob_sha256"], row["page"], row["figure_label"]))
        for n, row in enumerate(rows)
        if row["caption"] and row["figure_label"] and row["blob_sha256"]
    ]
    if not wanted:
        return {}
    keys = {key for _, key in wanted}
    drawn = {
        (f.blob_sha256, f.page, f.label): f.png
        for f in db.scalars(
            select(Figure).where(
                tuple_(Figure.blob_sha256, Figure.page, Figure.label).in_(keys)
            )
        )
    }
    return {n: (drawn[key], rows[n]["chunk_text"]) for n, key in wanted if key in drawn}


def _rerank(
    ml: MLClient,
    model: str,
    query: str,
    passages: list[Passage],
    texts: list[str],
    drawn: dict[int, tuple[bytes, str]] | None = None,
) -> list[Passage]:
    """The hits in the reranker's order; in the usual order if the reranker
    fails or takes too long. ``drawn``: hits reranked by their figure (image
    and caption), by place."""
    drawn = drawn or {}
    plain = [n for n in range(len(passages)) if n not in drawn]
    pictured = sorted(drawn)
    started = time.perf_counter()
    try:
        found = ml.rerank(
            query,
            [texts[n] for n in plain],
            model=model,
            timeout=RERANK_TIMEOUT,
            figures=[drawn[n] for n in pictured],
        )
    except (MLUnavailable, MLRejected) as error:
        log.warning("reranking unavailable, usual order: %s", error)
        return passages
    by_place = dict(zip(plain + pictured, found, strict=True))
    scores = [by_place[n] for n in range(len(passages))]
    seconds = time.perf_counter() - started
    metrics.ML_SECONDS.labels("rerank").observe(seconds)
    _measured(model, seconds, len(passages))
    for passage, score in zip(passages, scores, strict=True):
        passage.score = score
        passage.reranked = True
    return sorted(passages, key=lambda p: p.score, reverse=True)


def _per_item(passages: list[Passage], per_item: int | None) -> list[Passage]:
    """At most ``per_item`` hits per paper or note, in their order."""
    if per_item is None:
        return passages
    taken: dict[uuid.UUID | None, int] = {}
    result = []
    for passage in passages:
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


def _add_figures(db: Session, passages: list[Passage]) -> None:
    """Whether a caption's figure was found on its page (its image then at
    ``/api/files/{file_id}/figure``)."""
    files = {p.file_id for p in passages if p.figure and p.file_id is not None}
    if not files:
        return
    layouts: dict[uuid.UUID, list[dict[str, Any]]] = {
        file_id: pages
        for file_id, pages in db.execute(
            select(File.id, PageLayouts.pages)
            .join(PageLayouts, PageLayouts.blob_sha256 == File.blob_sha256)
            .where(File.id.in_(files))
        )
    }
    for passage in passages:
        pages = layouts.get(passage.file_id) if passage.file_id else None
        if pages and passage.page and passage.figure:
            figure = page_layout.captioned(pages, passage.page, passage.figure)
            if figure is not None:
                passage.figure_image = True
                passage.figure_top = figure["y"]
                passage.figure_left = figure["x"]
                passage.figure_width = figure["width"]
                passage.figure_height = figure["height"]


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
    figures: bool = False,
) -> list[Passage]:
    """Passages for ``q`` in the libraries the person can read (or one
    ``library``): its words (quotes for phrases, ``-`` to exclude), its
    meaning, or both; ``type`` (repeatable, CSL types) limits the items.
    ``per_item`` keeps the best few per paper or note, so more papers fit;
    ``item`` searches within one paper; ``archived=true`` includes the
    archive; ``figures=true`` finds figures and tables only (by their
    captions). The ``X-Search-Mode`` header says
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
        figures=figures,
    )
    response.headers["X-Search-Mode"] = used
    return passages
