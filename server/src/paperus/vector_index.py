"""HNSW indexes on the vectors (#61): one per model's vectors, for
passages (``embeddings``) and figures (``figure_embeddings``), made in the
background once a model has ``MIN_VECTORS`` of them; search by meaning
can take its nearest passages through it (``api.search``: ``near``; the
planner chooses), else compares with all of them (exact). Approximate:
98.5 % of the 1,000 nearest are the exact ones.

Below ``MIN_VECTORS`` an index does not pay: on the dev library (39,000
Qwen3-VL vectors) reading all of them took 105 ms, an index search for the
nearest 1,000 (the 304 MB index not fitting in PostgreSQL's 128 MB of
shared buffers) 93-200 ms; PostgreSQL rightly read them all. With ten and
a hundred times as many, reading all takes seconds (#61 measures where an
index starts to pay, and how much).

Each index is partial (``WHERE model = '…'``, the vectors name) on the
vectors cast to their dimensions (the column holds several models'), so
the search sorts by that same expression. Indexes of vectors no longer in
use are dropped."""

import hashlib
import logging
import re

from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

TABLES = ("embeddings", "figure_embeddings")
MIN_VECTORS = 100_000
"""Fewer (about 1,000 papers): compared with all of them, no index to keep
(it would also slow down adding vectors)."""
MEMORY = "512MB"
"""``maintenance_work_mem`` while building (more: quicker, less on disk). A
parallel build keeps its graph in shared memory: below the database
container's (``shm_size: 1gb`` in deploy/compose.yaml; 1 GB itself did not
fit with the overhead)."""
EF_SEARCH = 1000
"""Candidates an index search keeps: at least the nearest asked for
(``api.search.NEAREST``); pgvector's most."""
_PREFIX = "ix_hnsw_"
_SAFE = re.compile(r"^[\w.@:/+-]{1,64}$")


def index_name(table: str, model: str) -> str:
    """The index's name: the table and a hash of the vectors name (which may
    hold characters a name may not)."""
    digest = hashlib.sha256(model.encode()).hexdigest()[:12]
    return f"{_PREFIX}{table}_{digest}"


def _valid(db: Session, name: str) -> bool | None:
    """Whether the index exists and is usable (None: it does not exist;
    False: a build that failed or is still running left it)."""
    return db.scalar(
        text(
            "SELECT i.indisvalid FROM pg_index i"
            " JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :name"
        ),
        {"name": name},
    )


def needed(db: Session, model: str) -> list[str]:
    """The tables that want an index for ``model``'s vectors: enough of them
    and none (usable) yet. Counts no further than ``MIN_VECTORS``."""
    if not _SAFE.match(model):
        return []
    found = []
    for table in TABLES:
        if _valid(db, index_name(table, model)):
            continue
        enough = db.scalar(
            text(
                f"SELECT EXISTS (SELECT 1 FROM {table} WHERE model = :model"
                " OFFSET :skip)"
            ),
            {"model": model, "skip": MIN_VECTORS - 1},
        )
        if enough:
            found.append(table)
    return found


def stale(db: Session, models: list[str]) -> list[str]:
    """Indexes of vectors not in ``models`` (another model chosen)."""
    keep = {index_name(t, m) for t in TABLES for m in models}
    names = db.scalars(
        text("SELECT indexname FROM pg_indexes WHERE indexname LIKE :prefix"),
        {"prefix": f"{_PREFIX}%"},
    )
    return sorted(set(names) - keep)


def build(engine: Engine, table: str, model: str) -> bool:
    """Make the index for ``model``'s vectors in ``table`` (CONCURRENTLY:
    searches and embedding go on meanwhile); a failed one before it is
    dropped first. Whether there is one now."""
    if table not in TABLES or not _SAFE.match(model):
        return False
    name = index_name(table, model)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        dimensions = c.scalar(
            text(
                f"SELECT vector_dims(embedding) FROM {table} WHERE model = :m LIMIT 1"
            ),
            {"m": model},
        )
        if not dimensions:
            return False
        c.execute(text(f"SET maintenance_work_mem = '{MEMORY}'"))
        create = text(
            f"CREATE INDEX CONCURRENTLY {name} ON {table}"
            f" USING hnsw ((embedding::halfvec({int(dimensions)}))"
            f" halfvec_cosine_ops) WHERE model = '{model}'"
        )
        log.info("building %s for %s (%d dimensions)", name, model, dimensions)
        try:
            c.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
            c.execute(create)
        except OperationalError as error:
            if "shared memory" not in str(error):
                raise
            # Too little shared memory for a parallel build (Docker's 64 MB
            # default): slower, in the process's own memory.
            log.warning("building %s without parallel workers: %s", name, error)
            c.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
            c.execute(text("SET max_parallel_maintenance_workers = 0"))
            c.execute(create)
    return True


def drop(engine: Engine, name: str) -> None:
    """Drop one of these indexes (CONCURRENTLY)."""
    if not name.startswith(_PREFIX) or not re.fullmatch(r"\w+", name):
        return
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
