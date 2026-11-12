"""arXiv's version as the label of preprints whose PDF names it ("v2")

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-13 00:30:00.000000

Versions with an arXiv ID and no label whose main PDF is named after it
with a version ("2401.12345v2.pdf") get it as their label, as
``paperus.arxiv_versions`` labels the versions of new files.
"""

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"


def upgrade() -> None:
    op.execute(
        r"""
        UPDATE versions SET label = 'v' || (regexp_match(
            lower(f.filename),
            '(?:^|[^0-9.])' || replace(split_part(i.value, '/', -1), '.', '\.')
                || 'v([0-9]+)(?:\.pdf)?$'
        ))[1]::int
        FROM files f, identifiers i
        WHERE f.version_id = versions.id AND i.version_id = versions.id
          AND versions.label IS NULL
          AND i.scheme = 'arxiv' AND f.deleted_at IS NULL
          AND f.role = 'main' AND f.media_type = 'application/pdf'
          AND lower(f.filename) ~ ('(?:^|[^0-9.])'
              || replace(split_part(i.value, '/', -1), '.', '\.')
              || 'v[0-9]+(?:\.pdf)?$')
        """
    )


def downgrade() -> None:
    pass  # the labels may stay: they were free text before
