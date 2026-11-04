"""Keyword search over the text of files (search by meaning comes later)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text

from paperus.api.deps import DB, CurrentUser

router = APIRouter(tags=["search"])


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
    """HTML: the passage's text escaped, matches wrapped in ``<mark>``."""
    score: float


# Text is HTML-escaped before ts_headline adds <mark>, so snippets are safe
# to insert as HTML.
_SEARCH = text(
    """
    SELECT fc.file_id, fc.position, fc.page, f.version_id, i.id AS item_id,
           i.title AS item_title, ts_rank_cd(c.tsv, q) AS score,
           ts_headline(
               'simple',
               replace(replace(replace(c.text, '&', '&amp;'), '<', '&lt;'),
                       '>', '&gt;'),
               q,
               'StartSel=<mark>, StopSel=</mark>, MaxWords=40, MinWords=15,'
               ' MaxFragments=2, FragmentDelimiter=" … "'
           ) AS snippet
    FROM websearch_to_tsquery('simple', :query) AS q,
         chunks c
         JOIN file_chunks fc ON fc.chunk_sha256 = c.sha256
         JOIN files f ON f.id = fc.file_id
         JOIN versions v ON v.id = f.version_id
         JOIN items i ON i.id = v.item_id
    WHERE c.tsv @@ q AND f.deleted_at IS NULL AND i.deleted_at IS NULL
    ORDER BY score DESC, fc.file_id, fc.position
    LIMIT :limit
    """
)


@router.get("/api/search")
def search(
    db: DB,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[Passage]:
    """Passages matching the words in ``q`` (quotes for phrases, ``-`` to exclude)."""
    rows = db.execute(_SEARCH, {"query": q, "limit": limit}).mappings()
    return [
        Passage(passage_id=f"{row['file_id']}#{row['position']}", **row) for row in rows
    ]
