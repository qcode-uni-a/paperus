"""Change numbers for annotations and reading positions (for syncing)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-11 07:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"


def upgrade() -> None:
    for table in ("annotations", "item_views"):
        op.add_column(
            table,
            sa.Column(
                "change", sa.BigInteger(), server_default=sa.text("0"), nullable=False
            ),
        )
        # What there is counts as changed now: a client that synced before
        # gets it all once.
        op.execute(
            f"UPDATE {table} SET change ="
            " (SELECT value FROM change_counters WHERE name = 'library')"
        )
        op.create_index(f"ix_{table}_change", table, ["change"])


def downgrade() -> None:
    for table in ("annotations", "item_views"):
        op.drop_index(f"ix_{table}_change", table_name=table)
        op.drop_column(table, "change")
