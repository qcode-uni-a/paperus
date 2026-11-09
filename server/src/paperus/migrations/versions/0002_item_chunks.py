"""Papers' details (title and abstract) as search passages

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-09 14:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"

# The papers there are, as ``paperus.details.text_of`` makes their passage:
# the title, then the abstract (if any). Their vectors follow in the
# embedding sweep.
DETAILS = """
WITH details AS (
    SELECT id,
           CASE WHEN abstract <> '' THEN title || E'\\n\\n' || abstract
                ELSE title END AS text
    FROM items WHERE title <> ''
)
SELECT id, text, sha256(convert_to(text, 'UTF8')) AS sha256 FROM details
"""


def upgrade() -> None:
    op.create_table(
        "item_chunks",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunk_sha256"],
            ["chunks.sha256"],
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_index(
        op.f("ix_item_chunks_chunk_sha256"),
        "item_chunks",
        ["chunk_sha256"],
        unique=False,
    )
    op.execute(
        f"INSERT INTO chunks (sha256, text) SELECT DISTINCT sha256, text "
        f"FROM ({DETAILS}) d ON CONFLICT DO NOTHING"
    )
    op.execute(
        f"INSERT INTO item_chunks (item_id, chunk_sha256) SELECT id, sha256 "
        f"FROM ({DETAILS}) d"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_item_chunks_chunk_sha256"), table_name="item_chunks")
    op.drop_table("item_chunks")
