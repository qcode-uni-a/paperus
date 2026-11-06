"""Add what Manage → Missing needs: whether a paper wants a file, and the
last try to download an open-access copy

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-07 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column(
            "file_wanted", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )
    op.add_column(
        "items",
        sa.Column("open_access_tried_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("items", sa.Column("open_access_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "open_access_error")
    op.drop_column("items", "open_access_tried_at")
    op.drop_column("items", "file_wanted")
