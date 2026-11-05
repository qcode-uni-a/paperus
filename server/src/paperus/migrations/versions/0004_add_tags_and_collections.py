"""Add tags and collections

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05 10:17:19.862115
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "change", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tags_change"), "tags", ["change"], unique=False)
    op.create_index(
        "ix_tags_name_lower", "tags", [sa.literal_column("lower(name)")], unique=True
    )
    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "change", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_id"], ["collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_collections_change"), "collections", ["change"], unique=False
    )
    op.create_index(
        op.f("ix_collections_parent_id"), "collections", ["parent_id"], unique=False
    )
    op.create_table(
        "collection_items",
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("collection_id", "item_id"),
    )
    op.create_index(
        op.f("ix_collection_items_item_id"),
        "collection_items",
        ["item_id"],
        unique=False,
    )
    op.create_table(
        "item_tags",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "tag_id"),
    )
    op.create_index(op.f("ix_item_tags_tag_id"), "item_tags", ["tag_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_item_tags_tag_id"), table_name="item_tags")
    op.drop_table("item_tags")
    op.drop_index(op.f("ix_collection_items_item_id"), table_name="collection_items")
    op.drop_table("collection_items")
    op.drop_index(op.f("ix_collections_parent_id"), table_name="collections")
    op.drop_index(op.f("ix_collections_change"), table_name="collections")
    op.drop_table("collections")
    op.drop_index("ix_tags_name_lower", table_name="tags")
    op.drop_index(op.f("ix_tags_change"), table_name="tags")
    op.drop_table("tags")
