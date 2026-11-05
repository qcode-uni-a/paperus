"""Mark reference lists

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05 10:13:02.154155
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"


def upgrade() -> None:
    op.add_column(
        "file_chunks",
        sa.Column(
            "in_references",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("file_chunks", "in_references")
