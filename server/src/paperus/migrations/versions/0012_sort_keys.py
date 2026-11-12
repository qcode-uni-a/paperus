"""A paper's first author and journal, for sorting the library by them

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-12 18:00:00.000000

Filled in for the papers there are as ``library.refresh_item`` keeps them:
from the preferred version's details (pinned, else published > accepted >
edition > submitted > preprint > draft > other, newest first) with the
paper's own edits over them.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"


def upgrade() -> None:
    op.add_column("items", sa.Column("first_author", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("journal", sa.Text(), nullable=True))
    op.execute(
        """
        WITH preferred AS (
            SELECT DISTINCT ON (item_id) item_id, csl
            FROM versions
            ORDER BY item_id, pinned DESC,
                CASE kind
                    WHEN 'published' THEN 0 WHEN 'accepted' THEN 1
                    WHEN 'edition' THEN 2 WHEN 'submitted' THEN 3
                    WHEN 'preprint' THEN 4 WHEN 'draft' THEN 5 ELSE 6
                END,
                id DESC
        ),
        cited AS (
            SELECT items.id,
                CASE WHEN items.overrides ? 'author' THEN items.overrides -> 'author'
                     ELSE preferred.csl -> 'author' END AS author,
                CASE WHEN items.overrides ? 'container-title'
                     THEN items.overrides -> 'container-title'
                     ELSE preferred.csl -> 'container-title' END AS venue
            FROM items LEFT JOIN preferred ON preferred.item_id = items.id
        )
        UPDATE items SET
            first_author = (
                SELECT CASE WHEN person ? 'family'
                    THEN concat_ws(', ', person ->> 'family',
                                   nullif(person ->> 'given', ''))
                    ELSE person ->> 'literal' END
                FROM jsonb_array_elements(
                    CASE WHEN jsonb_typeof(cited.author) = 'array'
                         THEN cited.author ELSE '[]'::jsonb END
                ) WITH ORDINALITY AS listed(person, place)
                WHERE jsonb_typeof(person) = 'object'
                  AND (person ? 'family' OR coalesce(person ->> 'literal', '') <> '')
                ORDER BY place
                LIMIT 1
            ),
            journal = nullif(btrim(CASE jsonb_typeof(cited.venue)
                WHEN 'array' THEN cited.venue ->> 0
                WHEN 'string' THEN cited.venue #>> '{}'
            END), '')
        FROM cited
        WHERE cited.id = items.id
        """
    )


def downgrade() -> None:
    op.drop_column("items", "journal")
    op.drop_column("items", "first_author")
