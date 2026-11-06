"""Add smart collections (rules) and each item's year (for their rules)

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-06 23:00:00.000000
"""

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"

# As paperus.library at this revision: which version's details an item shows.
KINDS = ["published", "accepted", "edition", "submitted", "preprint", "draft", "other"]


def _year(csl: dict[str, Any]) -> int | None:
    for key in ("issued", "published-print", "published-online"):
        try:
            return int(csl[key]["date-parts"][0][0])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return None


def upgrade() -> None:
    op.add_column("collections", sa.Column("rules", postgresql.JSONB(), nullable=True))
    op.add_column("items", sa.Column("year", sa.Integer(), nullable=True))
    op.create_index("ix_items_year", "items", ["year"])
    connection = op.get_bind()
    overrides = {
        item_id: edits
        for item_id, edits in connection.execute(
            sa.text("SELECT id, overrides FROM items")
        )
    }
    shown: dict[Any, tuple[tuple[int, int, str], dict[str, Any]]] = {}
    for item_id, version_id, kind, pinned, csl in connection.execute(
        sa.text("SELECT item_id, id, kind, pinned, csl FROM versions")
    ):
        rank = KINDS.index(kind) if kind in KINDS else len(KINDS)
        # Pinned first, then by kind, newest first (ids grow with time).
        key = (0 if pinned else 1, rank, str(version_id))
        best = shown.get(item_id)
        if (
            best is None
            or key[:2] < best[0][:2]
            or (key[:2] == best[0][:2] and key[2] > best[0][2])
        ):
            shown[item_id] = (key, csl or {})
    for item_id, (_, csl) in shown.items():
        merged = dict(csl)
        for field, value in (overrides.get(item_id) or {}).items():
            if value is None:
                merged.pop(field, None)
            else:
                merged[field] = value
        year = _year(merged)
        if year is not None:
            connection.execute(
                sa.text("UPDATE items SET year = :year WHERE id = :id"),
                {"year": year, "id": item_id},
            )


def downgrade() -> None:
    op.drop_index("ix_items_year", table_name="items")
    op.drop_column("items", "year")
    op.drop_column("collections", "rules")
