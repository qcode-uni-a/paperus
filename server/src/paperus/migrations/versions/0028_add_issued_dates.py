"""Add the days each paper's publication date stands for (smart collections'
date rules)

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-07 19:00:00.000000
"""

import calendar
from datetime import date
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"

# As paperus chose the shown version when this migration was written (a
# frozen copy: later changes to paperus.library do not change it).
_RANK = {
    kind: rank
    for rank, kind in enumerate(
        ["published", "accepted", "edition", "submitted", "preprint", "draft", "other"]
    )
}


def _day_range(parts: list[int]) -> tuple[date, date] | None:
    if not parts or not 1 <= parts[0] <= 9999:
        return None
    year = parts[0]
    month = parts[1] if len(parts) > 1 and 1 <= parts[1] <= 12 else None
    if month is None:
        return date(year, 1, 1), date(year, 12, 31)
    last = calendar.monthrange(year, month)[1]
    day = parts[2] if len(parts) > 2 and 1 <= parts[2] <= last else None
    if day is None:
        return date(year, month, 1), date(year, month, last)
    return date(year, month, day), date(year, month, day)


def _issued(csl: dict[str, Any]) -> tuple[date, date] | None:
    for key in ("issued", "published-print", "published-online"):
        try:
            parts = csl[key]["date-parts"]
            start = _day_range([int(p) for p in parts[0]])
            end = _day_range([int(p) for p in parts[-1]])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if start and end:
            return start[0], max(start[1], end[1])
    return None


def upgrade() -> None:
    op.add_column("items", sa.Column("issued_from", sa.Date(), nullable=True))
    op.add_column("items", sa.Column("issued_to", sa.Date(), nullable=True))
    op.create_index(op.f("ix_items_issued_from"), "items", ["issued_from"])
    op.create_index(op.f("ix_items_issued_to"), "items", ["issued_to"])

    connection = op.get_bind()
    versions: dict[Any, list[Any]] = {}
    for row in connection.execute(
        sa.text("SELECT item_id, id, kind, pinned, csl FROM versions")
    ):
        versions.setdefault(row.item_id, []).append(row)
    updates = []
    for item_id, overrides in connection.execute(
        sa.text("SELECT id, overrides FROM items")
    ):
        rows = versions.get(item_id, [])
        pinned = [v for v in rows if v.pinned]
        newest_first = sorted(rows, key=lambda v: str(v.id), reverse=True)
        chosen = (
            pinned[0]
            if pinned
            else (
                min(newest_first, key=lambda v: _RANK.get(v.kind, 99)) if rows else None
            )
        )
        csl = dict(chosen.csl or {}) if chosen else {}
        for key, value in (overrides or {}).items():
            if value is None:
                csl.pop(key, None)
            else:
                csl[key] = value
        issued = _issued(csl)
        if issued:
            updates.append({"id": item_id, "start": issued[0], "end": issued[1]})
    if updates:
        connection.execute(
            sa.text(
                "UPDATE items SET issued_from = :start, issued_to = :end WHERE id = :id"
            ),
            updates,
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_items_issued_to"), table_name="items")
    op.drop_index(op.f("ix_items_issued_from"), table_name="items")
    op.drop_column("items", "issued_to")
    op.drop_column("items", "issued_from")
