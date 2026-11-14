"""Which files are embedded with which model

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-14 22:00:00.000000

``embedded_files``: a file whose passages (outside its reference list) all
have a model's vectors; the sweep for missing vectors looks at the files
without one instead of at all passages every ten minutes. Filled in here
for every model whose vectors are stored.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"


def upgrade() -> None:
    op.create_table(
        "embedded_files",
        sa.Column(
            "file_id",
            sa.Uuid(),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model", sa.String(64), primary_key=True),
    )
    op.execute(
        "INSERT INTO embedded_files (file_id, model)"
        " SELECT f.id, m.model"
        " FROM files f, (SELECT DISTINCT model FROM embeddings) m"
        " WHERE f.text_status = 'done'"
        " AND NOT EXISTS ("
        "   SELECT 1 FROM file_chunks fc"
        "   WHERE fc.file_id = f.id AND NOT fc.in_references"
        "   AND NOT EXISTS ("
        "     SELECT 1 FROM embeddings e"
        "     WHERE e.chunk_sha256 = fc.chunk_sha256 AND e.model = m.model))"
    )


def downgrade() -> None:
    op.drop_table("embedded_files")
