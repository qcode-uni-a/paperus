"""Add the university login's subject to users

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-05 21:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"


def upgrade() -> None:
    op.add_column("users", sa.Column("oidc_subject", sa.String(500), nullable=True))
    op.create_unique_constraint("users_oidc_subject_key", "users", ["oidc_subject"])


def downgrade() -> None:
    op.drop_constraint("users_oidc_subject_key", "users", type_="unique")
    op.drop_column("users", "oidc_subject")
