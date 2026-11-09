"""Where a person stopped reading a paper (to go on from there)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09 22:23:11.589082
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"


def upgrade() -> None:
    op.add_column(
        "item_views",
        sa.Column("reading", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("item_views", "reading")
