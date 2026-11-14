"""Figures as images, for multimodal search

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-14 16:00:00.000000

``file_chunks.figure``: what a caption passage labels ("FIG. 3", as
``page_layout.figure_label`` writes it), so search finds the caption's
figure; filled in for captions read before. ``figures``: a PDF content's
figures (by page and caption label) drawn as small images, once, for the
models that take images; ``figure_embeddings``: their vectors per model.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC

revision: str = "0024"
down_revision: str | None = "0023"

# page_layout._LABEL, as SQL: the label at a caption's start, its spaces
# collapsed into one each.
LABEL = r"^\W*((?:fig(?:ure)?|table|tab|abb(?:ildung)?)\.?\s*(?:\d+|[IVX]+)[a-z]?)"


def upgrade() -> None:
    op.add_column("file_chunks", sa.Column("figure", sa.String(40), nullable=True))
    op.execute(
        sa.text(
            "UPDATE file_chunks fc"
            " SET figure = regexp_replace((regexp_match(c.text, :label, 'i'))[1],"
            " '\\s+', ' ', 'g')"
            " FROM chunks c WHERE c.sha256 = fc.chunk_sha256 AND fc.caption"
        ).bindparams(label=LABEL)
    )
    op.create_table(
        "figures",
        sa.Column(
            "blob_sha256",
            sa.LargeBinary(),
            sa.ForeignKey("blobs.sha256", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("page", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(40), primary_key=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("png", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "figure_embeddings",
        sa.Column("blob_sha256", sa.LargeBinary(), primary_key=True),
        sa.Column("page", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(40), primary_key=True),
        sa.Column("model", sa.String(64), primary_key=True),
        sa.Column("embedding", HALFVEC(), nullable=False),
        sa.ForeignKeyConstraint(
            ["blob_sha256", "page", "label"],
            ["figures.blob_sha256", "figures.page", "figures.label"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_figure_embeddings_model", "figure_embeddings", ["model"])


def downgrade() -> None:
    op.drop_index("ix_figure_embeddings_model", "figure_embeddings")
    op.drop_table("figure_embeddings")
    op.drop_table("figures")
    op.drop_column("file_chunks", "figure")
