"""Add seen hints to users

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-05 23:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "seen_hints",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "seen_hints")
