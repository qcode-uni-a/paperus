"""Libraries' automations, and their members' papers already handled

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-13 23:30:00.000000

``libraries.automations``: what an owner (a person, a group's admins)
switched off or on of what paperus does by itself for its papers
(``paperus.automations``; unset: the default).
``libraries.own_papers_seen``: the DOIs of its people's works (OpenAlex)
the daily job has added or found already, never to be added again (one
removed stays removed). Existing libraries start with neither.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"


def upgrade() -> None:
    op.add_column(
        "libraries",
        sa.Column(
            "automations",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "libraries",
        sa.Column(
            "own_papers_seen",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("libraries", "own_papers_seen")
    op.drop_column("libraries", "automations")
