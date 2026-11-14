"""The SQL paperus sends for its most used and its periodic queries, kept
in ``server/sql/`` (one file a case, as sent, formatted): a change to a
query shows there in the diff as SQL, not only as SQLAlchemy code. Out of
date: this test fails; write them anew with

    PAPERUS_WRITE_SQL=1 uv run pytest tests/test_sql.py

(No ``NOT IN`` with a subquery anywhere: ``conftest.no_not_in_subqueries``.)"""

import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import sqlparse
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import ClauseElement

from paperus import figures
from paperus.embedding import (
    details_missing_embeddings,
    embed_file,
    files_missing_embeddings,
    notes_missing_embeddings,
)
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.conftest import SERVER_DIR, FakeML
from tests.test_meaning import MODEL, add_file

SQL_DIR = SERVER_DIR / "sql"
WRITE = bool(os.environ.get("PAPERUS_WRITE_SQL"))

Case = Callable[[TestClient, Session, str], object]


def _sweeps(client: TestClient, db: Session, item: str) -> None:
    files_missing_embeddings(db, MODEL)
    notes_missing_embeddings(db, MODEL)
    details_missing_embeddings(db, MODEL, limit=1)
    figures.missing(db, MODEL)


CASES: dict[str, Case] = {
    "search": lambda c, db, item: c.get("/api/search", params={"q": "gaps"}),
    "search_figures": lambda c, db, item: c.get(
        "/api/search", params={"q": "gaps", "figures": "true"}
    ),
    "similar_papers": lambda c, db, item: c.get(f"/api/items/{item}/similar"),
    "paper_list": lambda c, db, item: c.get("/api/items", params={"limit": 50}),
    "embedding_sweeps": _sweeps,
}


@pytest.fixture
def sent() -> Iterator[list[str]]:
    """The statements any engine sends meanwhile, as compiled (lists of
    values as placeholders), each once (kept sorted: the ORM loads related
    rows in varying order)."""
    seen: list[str] = []

    def grab(
        conn: Any,  # noqa: ANN401
        clause: object,
        multiparams: object,
        params: object,
        options: object,
    ) -> None:
        if isinstance(clause, ClauseElement):
            sql = str(clause.compile(dialect=conn.dialect))
            if sql not in seen:
                seen.append(sql)

    event.listen(Engine, "before_execute", grab)
    yield seen
    event.remove(Engine, "before_execute", grab)


@pytest.mark.parametrize("name", sorted(CASES))
def test_sql_as_kept(
    name: str,
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    fake_ml: FakeML,
    sent: list[str],
) -> None:
    file = add_file(logged_in, "Notes")
    process_file(db, blobs, uuid.UUID(file["id"]))
    embed_file(db, fake_ml.client(), MODEL, uuid.UUID(file["id"]))
    item = str(db.scalar(text("SELECT id FROM items LIMIT 1")))
    sent.clear()
    CASES[name](logged_in, db, item)
    formatted = [
        "\n".join(
            line.rstrip()
            for line in sqlparse.format(sql, reindent=True, keyword_case="upper")
            .strip()
            .splitlines()
        )
        + ";"
        for sql in sorted(sent)
    ]
    title = name.replace("_", " ")
    kept = f"-- The SQL paperus sends for: {title} (tests/test_sql.py)\n\n"
    kept += "\n\n".join(formatted) + "\n"
    path = SQL_DIR / f"{name}.sql"
    if WRITE:
        SQL_DIR.mkdir(exist_ok=True)
        path.write_text(kept)
    update = "PAPERUS_WRITE_SQL=1 uv run pytest tests/test_sql.py"
    assert path.exists() and path.read_text() == kept, f"{path.name}: {update}"


def test_not_in_with_a_subquery_is_refused(db: Session) -> None:
    with pytest.raises(AssertionError, match="NOT EXISTS"):
        db.execute(select(text("1")).where(text("1 NOT IN (SELECT 2)")))
