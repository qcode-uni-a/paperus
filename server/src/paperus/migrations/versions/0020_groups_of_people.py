"""Groups of a few people, made by sharing with someone

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-13 22:00:00.000000

``groups.people``: a group made by sharing a paper with someone ("Anna &
Ben", #16), not by an administrator. Existing groups are none of these.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"


def upgrade() -> None:
    op.add_column(
        "groups",
        sa.Column("people", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("groups", "people")
