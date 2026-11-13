"""When each person last used paperus ("last active")

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-13 14:30:00.000000

"Last login" is only when someone logged in with a password or OIDC; a
session lasts weeks, and the app, the extension and assistants use
tokens. ``users.last_active_at`` is any use; it starts as the latest of
the last login and the last use of the person's access tokens.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        """
        UPDATE users SET last_active_at = greatest(
            last_login_at,
            (SELECT max(t.last_used_at) FROM access_tokens t
             WHERE t.user_id = users.id)
        )
        """
    )


def downgrade() -> None:
    op.drop_column("users", "last_active_at")
