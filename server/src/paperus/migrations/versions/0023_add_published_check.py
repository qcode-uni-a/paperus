"""Add when each paper was last checked for a published version

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-07 00:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("published_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("items", "published_checked_at")
