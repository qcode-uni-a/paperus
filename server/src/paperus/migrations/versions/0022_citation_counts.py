"""How often papers are cited (OpenAlex), and when that was looked up

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-14 01:00:00.000000

``items.cited_by_count``: the paper's citations as OpenAlex counts them
(``paperus.citation_counts``), renewed each week; ``citations_checked_at``:
when. Existing papers start with neither: the first count is looked up
soon, and celebrates nothing (milestones are passed from then on).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"


def upgrade() -> None:
    op.add_column("items", sa.Column("cited_by_count", sa.Integer(), nullable=True))
    op.add_column(
        "items",
        sa.Column("citations_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("items", "citations_checked_at")
    op.drop_column("items", "cited_by_count")
