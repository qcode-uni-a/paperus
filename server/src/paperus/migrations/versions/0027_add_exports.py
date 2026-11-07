"""Add exports (a person's library as SQLite and files) and imports of them
in several parts, with the owners chosen before applying

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-07 18:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"


def upgrade() -> None:
    op.create_table(
        "exports",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("done", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column(
            "parts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exports_user_id"), "exports", ["user_id"])
    op.add_column(
        "imports",
        sa.Column("choices", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "import_parts",
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("blob_sha256", sa.LargeBinary(length=32), nullable=True),
        sa.ForeignKeyConstraint(["blob_sha256"], ["blobs.sha256"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["import_id"], ["imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("import_id", "position"),
    )
    op.create_index(
        op.f("ix_import_parts_blob_sha256"), "import_parts", ["blob_sha256"]
    )


def downgrade() -> None:
    op.drop_table("import_parts")
    op.drop_column("imports", "choices")
    op.drop_table("exports")
