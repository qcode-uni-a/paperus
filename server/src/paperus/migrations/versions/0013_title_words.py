"""The words of papers' titles, indexed: papers whose titles share words

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-12 21:00:00.000000
"""

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_items_title_words ON items USING gin "
        "(tsvector_to_array(to_tsvector('english'::regconfig, title)))"
    )


def downgrade() -> None:
    op.drop_index("ix_items_title_words", table_name="items")
