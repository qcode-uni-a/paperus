"""Captions marked among a file's passages

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-14 10:00:00.000000

``file_chunks.caption``: the passage is a figure's or table's caption (cut
apart from the text since #43, ``page_layout.pieces_text``), found by
search as a figure. Existing ones are marked by how they begin ("FIG. 2.",
"Figure 3:", "Fig. 1 |", "TABLE I.", "Abbildung 4."), as the layout code
finds them.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"

CAPTION = r"^\W*(fig(ure)?|table|tab|abb(ildung)?)\.?\s*([0-9]+|[IVX]+)[a-z]?\s*[.:|]"


def upgrade() -> None:
    op.add_column(
        "file_chunks",
        sa.Column("caption", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(
        sa.text(
            "UPDATE file_chunks fc SET caption = true FROM chunks c"
            " WHERE c.sha256 = fc.chunk_sha256 AND NOT fc.in_references"
            " AND c.text ~* :caption"
        ).bindparams(caption=CAPTION)
    )


def downgrade() -> None:
    op.drop_column("file_chunks", "caption")
