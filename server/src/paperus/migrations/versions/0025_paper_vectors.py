"""Papers' average vectors, for similar papers

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-14 21:00:00.000000

``paper_vectors``: each paper's passages' average vector per model (its
files' passages outside the trash and the reference list), with the
paper's change number it was computed at. Similar papers compared them
anew on every request (all visible papers' passages); filled in here for
the papers there are.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC

revision: str = "0025"
down_revision: str | None = "0024"


def upgrade() -> None:
    op.create_table(
        "paper_vectors",
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model", sa.String(64), primary_key=True),
        sa.Column("change", sa.BigInteger(), nullable=False),
        sa.Column("passages", sa.Integer(), nullable=False),
        sa.Column("embedding", HALFVEC(), nullable=True),
    )
    op.execute(
        "INSERT INTO paper_vectors (item_id, model, change, passages, embedding)"
        " SELECT i.id, e.model, i.change, count(*), avg(e.embedding)"
        " FROM items i"
        " JOIN versions v ON v.item_id = i.id"
        " JOIN files f ON f.version_id = v.id AND f.deleted_at IS NULL"
        " JOIN file_chunks fc ON fc.file_id = f.id AND NOT fc.in_references"
        " JOIN embeddings e ON e.chunk_sha256 = fc.chunk_sha256"
        " WHERE i.deleted_at IS NULL"
        " GROUP BY i.id, e.model, i.change"
    )


def downgrade() -> None:
    op.drop_table("paper_vectors")
