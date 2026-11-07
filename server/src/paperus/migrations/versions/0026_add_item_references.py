"""Add papers' reference lists

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-07 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("references_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "items", sa.Column("references_source", sa.String(length=16), nullable=True)
    )
    op.create_table(
        "item_references",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("authors", sa.String(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("container", sa.String(), nullable=True),
        sa.Column("doi", sa.String(), nullable=True),
        sa.Column("arxiv", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "position"),
    )
    op.create_index(op.f("ix_item_references_doi"), "item_references", ["doi"])
    op.create_index(op.f("ix_item_references_arxiv"), "item_references", ["arxiv"])


def downgrade() -> None:
    op.drop_table("item_references")
    op.drop_column("items", "references_source")
    op.drop_column("items", "references_checked_at")
