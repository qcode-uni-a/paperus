"""What was deleted for good, for syncing

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-11 08:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"


def upgrade() -> None:
    op.create_table(
        "removals",
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("library_id", sa.Uuid(), nullable=False),
        sa.Column("change", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("record_id"),
    )
    op.create_index("ix_removals_change", "removals", ["change"])
    op.create_index("ix_removals_library_id", "removals", ["library_id"])


def downgrade() -> None:
    op.drop_table("removals")
