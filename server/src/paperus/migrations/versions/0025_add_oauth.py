"""Add OAuth for connected apps (MCP connectors)

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-07 03:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"


def _record() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        *_record(),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "redirect_uris", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )
    op.create_table(
        "oauth_codes",
        *_record(),
        sa.Column("code_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("redirect_uri", sa.String(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index(op.f("ix_oauth_codes_client_id"), "oauth_codes", ["client_id"])
    op.create_index(op.f("ix_oauth_codes_user_id"), "oauth_codes", ["user_id"])
    op.create_table(
        "oauth_grants",
        *_record(),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("refresh_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_hash"),
    )
    op.create_index(op.f("ix_oauth_grants_client_id"), "oauth_grants", ["client_id"])
    op.create_index(op.f("ix_oauth_grants_user_id"), "oauth_grants", ["user_id"])
    op.add_column("access_tokens", sa.Column("grant_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_access_tokens_grant_id"), "access_tokens", ["grant_id"])
    op.create_foreign_key(
        "access_tokens_grant_id_fkey",
        "access_tokens",
        "oauth_grants",
        ["grant_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "access_tokens_grant_id_fkey",
        "access_tokens",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_access_tokens_grant_id"), table_name="access_tokens")
    op.drop_column("access_tokens", "grant_id")
    op.drop_table("oauth_grants")
    op.drop_table("oauth_codes")
    op.drop_table("oauth_clients")
