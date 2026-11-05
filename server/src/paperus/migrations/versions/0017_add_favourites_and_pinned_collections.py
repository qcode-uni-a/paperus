"""Add favourites (starred papers) and pinned collections, per person

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-05 17:51:28.495691
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"


def upgrade() -> None:
    op.create_table(
        "favourites",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "item_id"),
    )
    op.create_index(
        op.f("ix_favourites_item_id"), "favourites", ["item_id"], unique=False
    )
    op.create_table(
        "pinned_collections",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "collection_id"),
    )
    op.create_index(
        op.f("ix_pinned_collections_collection_id"),
        "pinned_collections",
        ["collection_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_pinned_collections_collection_id"), table_name="pinned_collections"
    )
    op.drop_table("pinned_collections")
    op.drop_index(op.f("ix_favourites_item_id"), table_name="favourites")
    op.drop_table("favourites")
