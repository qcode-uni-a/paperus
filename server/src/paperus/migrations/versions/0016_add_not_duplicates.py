"""Add not_duplicates: pairs of papers someone said are different

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-05 17:40:52.239703
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"


def upgrade() -> None:
    op.create_table(
        "not_duplicates",
        sa.Column("item_a", sa.Uuid(), nullable=False),
        sa.Column("item_b", sa.Uuid(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_a"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_b"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_a", "item_b"),
    )
    op.create_index(
        op.f("ix_not_duplicates_item_b"), "not_duplicates", ["item_b"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_not_duplicates_item_b"), table_name="not_duplicates")
    op.drop_table("not_duplicates")
