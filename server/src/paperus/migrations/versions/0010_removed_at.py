"""When something was removed (removals are kept a year)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-11 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"


def upgrade() -> None:
    op.add_column(
        "removals",
        sa.Column(
            "removed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("removals", "removed_at")
