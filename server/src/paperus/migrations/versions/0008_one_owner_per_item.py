"""One owner per item

Items belong to one owner again: a person or a group (through their
library). Items in several libraries keep a group's, else the first one.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05 21:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"


def upgrade() -> None:
    op.add_column("items", sa.Column("library_id", sa.Uuid(), nullable=True))
    op.execute("""
        UPDATE items SET library_id = (
            SELECT il.library_id
            FROM item_libraries il JOIN libraries l ON l.id = il.library_id
            WHERE il.item_id = items.id
            ORDER BY (l.group_id IS NULL), il.created_at
            LIMIT 1
        )
    """)
    # Items that were in no library (cannot happen, but never lose them):
    # their adder's library.
    op.execute("""
        UPDATE items SET library_id = libraries.id
        FROM libraries
        WHERE items.library_id IS NULL AND libraries.user_id = items.added_by
    """)
    op.alter_column("items", "library_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_items_library_id_libraries"),
        "items",
        "libraries",
        ["library_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_items_library_id"), "items", ["library_id"])
    op.drop_index(op.f("ix_item_libraries_library_id"), table_name="item_libraries")
    op.drop_table("item_libraries")


def downgrade() -> None:
    raise NotImplementedError(
        "going back to several libraries per item is not supported"
    )
