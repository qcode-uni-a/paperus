"""Recent activity: when items changed, when people opened them

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-06 00:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Until now only the creation time is known.
    op.execute("UPDATE items SET changed_at = created_at")
    op.create_index(op.f("ix_items_changed_at"), "items", ["changed_at"])
    op.create_table(
        "item_views",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "item_id"),
    )
    op.create_index(op.f("ix_item_views_item_id"), "item_views", ["item_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_item_views_item_id"), table_name="item_views")
    op.drop_table("item_views")
    op.drop_index(op.f("ix_items_changed_at"), table_name="items")
    op.drop_column("items", "changed_at")
