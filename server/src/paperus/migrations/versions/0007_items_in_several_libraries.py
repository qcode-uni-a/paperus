"""Items in several libraries

A paper exists once and can be in a person's library and in groups'
libraries at the same time; each item's library so far becomes its first
link.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-05 20:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"


def upgrade() -> None:
    op.create_table(
        "item_libraries",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("library_id", sa.Uuid(), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "library_id"),
    )
    op.create_index(
        op.f("ix_item_libraries_library_id"), "item_libraries", ["library_id"]
    )
    op.execute("""
        INSERT INTO item_libraries (item_id, library_id, added_by, created_at)
        SELECT id, library_id, added_by, created_at FROM items
    """)
    op.drop_index(op.f("ix_items_library_id"), table_name="items")
    op.drop_constraint("fk_items_library_id_libraries", "items", type_="foreignkey")
    op.drop_column("items", "library_id")


def downgrade() -> None:
    raise NotImplementedError("items in several libraries cannot be undone")
