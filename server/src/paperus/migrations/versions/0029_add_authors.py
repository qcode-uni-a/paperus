"""Add authors: people shared by the installation, each paper's authors
linked to them, and pairs said to be different people

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-07 23:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"


def upgrade() -> None:
    op.create_table(
        "authors",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("orcid", sa.String(length=19), nullable=True),
        sa.Column("openalex_id", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("orcid"),
        sa.UniqueConstraint("openalex_id"),
    )
    op.create_index(op.f("ix_authors_key"), "authors", ["key"])
    op.create_table(
        "authorships",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("written", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("affiliation", sa.String(), nullable=True),
        sa.Column("orcid", sa.String(length=19), nullable=True),
        sa.Column("openalex_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["authors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("item_id", "position"),
    )
    op.create_index(op.f("ix_authorships_author_id"), "authorships", ["author_id"])
    op.create_index(op.f("ix_authorships_key"), "authorships", ["key"])
    op.create_table(
        "authors_apart",
        sa.Column("first", sa.Uuid(), nullable=False),
        sa.Column("second", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["first"], ["authors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["second"], ["authors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("first", "second"),
    )
    op.add_column(
        "items", sa.Column("authors_key", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "items", sa.Column("authors_linked", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("items", "authors_linked")
    op.drop_column("items", "authors_key")
    op.drop_table("authors_apart")
    op.drop_table("authorships")
    op.drop_table("authors")
