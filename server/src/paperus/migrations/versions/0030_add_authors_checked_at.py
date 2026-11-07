"""Add when each paper's authors were looked up at OpenAlex

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-08 01:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("authors_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("items", "authors_checked_at")
