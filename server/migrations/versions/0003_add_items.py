"""Add items

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04 22:46:50.109065
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("doi", sa.String(), nullable=True),
        sa.Column("csl", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doi"),
    )


def downgrade() -> None:
    op.drop_table("items")
