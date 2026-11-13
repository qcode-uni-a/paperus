"""When paperus last looked for a paper's errata

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-13 21:00:00.000000

``items.errata_checked_at`` (``paperus.errata``): empty, so every paper
with a journal's DOI is looked at once, a few hundred a week.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("errata_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("items", "errata_checked_at")
