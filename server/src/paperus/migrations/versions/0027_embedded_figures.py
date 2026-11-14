"""Which PDFs' figures are embedded with which model

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-14 22:30:00.000000

``embedded_figures``: a PDF content whose current layouts' captioned
figures all have a model's vectors; the sweep for missing figure vectors
looks at the PDFs without one instead of into every PDF's layouts every
ten minutes. Filled in here for every model whose figure vectors are
stored.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"

LAYOUT_VERSION = 10
"""``page_layout.VERSION`` now: older layouts are made anew (and their
figures with them), so they are not marked."""


def upgrade() -> None:
    op.create_table(
        "embedded_figures",
        sa.Column(
            "blob_sha256",
            sa.LargeBinary(),
            sa.ForeignKey("blobs.sha256", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model", sa.String(64), primary_key=True),
    )
    op.execute(
        sa.text(
            "INSERT INTO embedded_figures (blob_sha256, model)"
            " SELECT pl.blob_sha256, m.model"
            " FROM page_layouts pl,"
            " (SELECT DISTINCT model FROM figure_embeddings) m"
            " WHERE pl.version = :version"
            " AND (SELECT count(DISTINCT (p.n, fig->>'caption'))"
            "      FROM jsonb_array_elements(pl.pages)"
            "           WITH ORDINALITY AS p(page, n),"
            "           jsonb_array_elements(coalesce(p.page->'figures', '[]'))"
            "           AS fig"
            "      WHERE fig ? 'caption')"
            " <= (SELECT count(*) FROM figure_embeddings fe"
            "     WHERE fe.blob_sha256 = pl.blob_sha256 AND fe.model = m.model)"
        ).bindparams(version=LAYOUT_VERSION)
    )


def downgrade() -> None:
    op.drop_table("embedded_figures")
