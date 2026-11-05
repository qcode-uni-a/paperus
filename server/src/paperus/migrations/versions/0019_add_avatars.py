"""Add profile pictures to users

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-05 22:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar", sa.LargeBinary(), nullable=True))
    op.add_column("users", sa.Column("avatar_type", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("avatar_version", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_version")
    op.drop_column("users", "avatar_type")
    op.drop_column("users", "avatar")
