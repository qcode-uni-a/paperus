"""Add blobs and files

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-04 22:49:34.531644
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"


def upgrade() -> None:
    op.create_table(
        "blobs",
        sa.Column("sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("sha256"),
    )
    op.create_table(
        "files",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("blob_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("version_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["blob_sha256"],
            ["blobs.sha256"],
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_files_blob_sha256"), "files", ["blob_sha256"], unique=False
    )
    op.create_index(op.f("ix_files_item_id"), "files", ["item_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_files_item_id"), table_name="files")
    op.drop_index(op.f("ix_files_blob_sha256"), table_name="files")
    op.drop_table("files")
    op.drop_table("blobs")
