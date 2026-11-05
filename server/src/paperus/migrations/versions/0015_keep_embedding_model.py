"""Keep bge-m3 where it is in use, as the default becomes arctic-embed-m-v2

Installations that never chose a model used the default, bge-m3; their
vectors would otherwise all be computed again after the update. Saving the
choice keeps them as they are (admins can switch under Machine learning).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-05 18:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO system_settings (key, value)
            SELECT 'config', '{"embedding_model": "bge-m3"}'::jsonb
            WHERE EXISTS (SELECT 1 FROM embeddings WHERE model = 'bge-m3')
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    # The saved choice is a setting like any other; leave it.
    pass
