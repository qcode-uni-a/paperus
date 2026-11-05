"""Users: last login and deactivation

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-06 01:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "deactivated_at")
    op.drop_column("users", "last_login_at")
