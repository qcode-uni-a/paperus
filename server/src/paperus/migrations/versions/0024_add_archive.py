"""Add the archive: papers kept, but left out of lists and search

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-07 02:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"


def upgrade() -> None:
    op.add_column(
        "items", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("items", "archived_at")
