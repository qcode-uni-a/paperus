"""Fluent mode's page layouts, worked out on the server

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10 16:20:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"


def upgrade() -> None:
    op.create_table(
        "page_layouts",
        sa.Column("blob_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("pages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["blob_sha256"], ["blobs.sha256"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("blob_sha256"),
    )


def downgrade() -> None:
    op.drop_table("page_layouts")
