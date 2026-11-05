"""Add tag colours and descriptions

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05 16:40:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"


def upgrade() -> None:
    op.add_column("tags", sa.Column("color", sa.String(length=16), nullable=True))
    op.add_column("tags", sa.Column("description", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tags", "description")
    op.drop_column("tags", "color")
