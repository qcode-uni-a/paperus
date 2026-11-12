"""Links of a paper: where its code, data and more are

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-12 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column(
            "links",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("items", "links")
