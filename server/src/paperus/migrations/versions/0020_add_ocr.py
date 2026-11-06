"""Add OCR: the text read from scanned pages, and each file's OCR state

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-06 21:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"

IMAGES = ("image/png", "image/jpeg", "image/tiff", "image/webp")


def upgrade() -> None:
    op.create_table(
        "ocr_pages",
        sa.Column(
            "blob_sha256",
            sa.LargeBinary(32),
            sa.ForeignKey("blobs.sha256", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("page", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "lines",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column("files", sa.Column("ocr_status", sa.String(16), nullable=True))
    op.create_index("ix_files_ocr_status", "files", ["ocr_status"])
    # Read again what may be scans: files without text, and images (which
    # were not read at all); their scanned pages then wait for OCR.
    images = ", ".join(f"'{media_type}'" for media_type in IMAGES)
    op.execute(
        "UPDATE files SET text_status = 'pending', text_error = NULL "
        "WHERE text_status = 'no_text' "
        f"OR (text_status = 'unsupported' AND media_type IN ({images}))"
    )


def downgrade() -> None:
    op.drop_index("ix_files_ocr_status", table_name="files")
    op.drop_column("files", "ocr_status")
    op.drop_table("ocr_pages")
