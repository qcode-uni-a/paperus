"""Papers' details passages with the abstract of their own details too

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09 18:00:00.000000

0002 took only the abstract found for a paper (``items.abstract``), not
the one in its details (from Crossref, an import or typed in), which the
paper shows first. Its passages are made again, as ``paperus.details``
makes them now (written out here, so later changes there leave this
migration as it was).
"""

import hashlib
import html
import re
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"

_RANK = {"published": 0, "preprint": 1}
_JATS = re.compile(r"</?(?:jats:)?[a-z][^>]*>")


def _plain(abstract: str) -> str:
    text = re.sub(r"</(?:jats:)?p>\s*", "\n\n", abstract)
    text = re.sub(r"<(?:jats:)?title>.*?</(?:jats:)?title>", "", text, flags=re.S)
    text = html.unescape(_JATS.sub("", text))
    paragraphs = [" ".join(p.split()) for p in text.split("\n\n")]
    return "\n\n".join(p for p in paragraphs if p)


def _abstract(item: sa.Row[Any], versions: list[sa.Row[Any]]) -> str | None:
    """The abstract the paper shows: its manual edit, else its preferred
    version's (pinned; else published before preprint before others,
    newest first), else the one found for it."""
    if "abstract" in item.overrides:
        return item.overrides["abstract"]
    pinned = [v for v in versions if v.pinned]
    newest_first = sorted(versions, key=lambda v: v.id, reverse=True)
    if pinned:
        preferred = pinned[0]
    elif versions:
        preferred = min(newest_first, key=lambda v: _RANK.get(v.kind, 2))
    else:
        return item.abstract
    if preferred.csl.get("abstract"):
        return str(preferred.csl["abstract"])
    return item.abstract


def upgrade() -> None:
    connection = op.get_bind()
    versions: dict[Any, list[sa.Row[Any]]] = {}
    for version in connection.execute(
        sa.text("SELECT id, item_id, kind, pinned, csl FROM versions ORDER BY id")
    ):
        versions.setdefault(version.item_id, []).append(version)
    for item in connection.execute(
        sa.text("SELECT id, title, abstract, overrides FROM items WHERE title <> ''")
    ):
        abstract = _abstract(item, versions.get(item.id, []))
        text = "\n\n".join(
            part
            for part in (item.title, _plain(abstract) if abstract else None)
            if part
        )
        sha256 = hashlib.sha256(text.encode()).digest()
        connection.execute(
            sa.text(
                "INSERT INTO chunks (sha256, text) VALUES (:sha256, :text) "
                "ON CONFLICT DO NOTHING"
            ),
            {"sha256": sha256, "text": text},
        )
        connection.execute(
            sa.text(
                "INSERT INTO item_chunks (item_id, chunk_sha256) "
                "VALUES (:id, :sha256) ON CONFLICT (item_id) "
                "DO UPDATE SET chunk_sha256 = :sha256"
            ),
            {"id": item.id, "sha256": sha256},
        )


def downgrade() -> None:
    """Nothing to undo: the passages stay as they are."""
