"""Initial schema (the migrations of 0.0.1 to 0.0.14, in one)

Revision ID: 0001
Revises:
Create Date: 2026-11-08 11:44:32.388039
"""

from pathlib import Path

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None

# Procrastinate's schema for the version we started with; later versions
# bring their own migration files.
PROCRASTINATE_SCHEMA = Path(__file__).parent.parent / "procrastinate_3.10.0.sql"

DROP_PROCRASTINATE = """
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables
             WHERE schemaname = 'public' AND tablename LIKE 'procrastinate%' LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', r.tablename);
    END LOOP;
    FOR r IN SELECT p.oid::regprocedure AS signature FROM pg_proc p
             JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public' AND p.proname LIKE 'procrastinate%' LOOP
        EXECUTE format('DROP FUNCTION IF EXISTS %s CASCADE', r.signature);
    END LOOP;
    FOR r IN SELECT t.typname FROM pg_type t
             JOIN pg_namespace n ON n.oid = t.typnamespace
             WHERE n.nspname = 'public' AND t.typname LIKE 'procrastinate%'
               AND t.typtype IN ('e', 'c') LOOP
        EXECUTE format('DROP TYPE IF EXISTS %I CASCADE', r.typname);
    END LOOP;
END $$;
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(PROCRASTINATE_SCHEMA.read_text())
    op.create_table(
        "authors",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("orcid", sa.String(length=19), nullable=True),
        sa.Column("openalex_id", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("openalex_id"),
        sa.UniqueConstraint("orcid"),
    )
    op.create_index(op.f("ix_authors_key"), "authors", ["key"], unique=False)
    op.create_table(
        "blobs",
        sa.Column("sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("sha256"),
    )
    op.create_table(
        "change_counters",
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "chunks",
        sa.Column("sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', text)", persisted=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("sha256"),
    )
    op.create_index(
        "ix_chunks_tsv", "chunks", ["tsv"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "redirect_uris", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column(
            "is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("default_library_id", sa.Uuid(), nullable=True),
        sa.Column(
            "seen_hints",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("oidc_subject", sa.String(length=500), nullable=True),
        sa.Column("avatar", sa.LargeBinary(), nullable=True),
        sa.Column("avatar_type", sa.String(length=32), nullable=True),
        sa.Column("avatar_version", sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("oidc_subject"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "authors_apart",
        sa.Column("first", sa.Uuid(), nullable=False),
        sa.Column("second", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["first"], ["authors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["second"], ["authors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("first", "second"),
    )
    op.create_table(
        "embeddings",
        sa.Column("chunk_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("embedding", HALFVEC(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunk_sha256"], ["chunks.sha256"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("chunk_sha256", "model"),
    )
    op.create_index(op.f("ix_embeddings_model"), "embeddings", ["model"], unique=False)
    op.create_table(
        "exports",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("done", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column(
            "parts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exports_user_id"), "exports", ["user_id"], unique=False)
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_id"], ["groups.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_groups_parent_id"), "groups", ["parent_id"], unique=False)
    op.create_table(
        "login_sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_login_sessions_user_id"), "login_sessions", ["user_id"], unique=False
    )
    op.create_table(
        "oauth_codes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("redirect_uri", sa.String(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"], ["oauth_clients.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index(
        op.f("ix_oauth_codes_client_id"), "oauth_codes", ["client_id"], unique=False
    )
    op.create_index(
        op.f("ix_oauth_codes_user_id"), "oauth_codes", ["user_id"], unique=False
    )
    op.create_table(
        "oauth_grants",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("refresh_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"], ["oauth_clients.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_hash"),
    )
    op.create_index(
        op.f("ix_oauth_grants_client_id"), "oauth_grants", ["client_id"], unique=False
    )
    op.create_index(
        op.f("ix_oauth_grants_user_id"), "oauth_grants", ["user_id"], unique=False
    )
    op.create_table(
        "ocr_pages",
        sa.Column("blob_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "lines",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["blob_sha256"], ["blobs.sha256"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("blob_sha256", "page"),
    )
    op.create_table(
        "access_tokens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("hint", sa.String(length=32), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "library_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grant_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["grant_id"], ["oauth_grants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_access_tokens_grant_id"), "access_tokens", ["grant_id"], unique=False
    )
    op.create_index(
        op.f("ix_access_tokens_user_id"), "access_tokens", ["user_id"], unique=False
    )
    op.create_table(
        "libraries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (group_id IS NULL)", name="ck_libraries_one_owner"
        ),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "memberships",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_index(
        op.f("ix_memberships_user_id"), "memberships", ["user_id"], unique=False
    )
    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("library_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "change", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["library_id"],
            ["libraries.id"],
            ondelete="CASCADE",
            name="fk_collections_library_id_libraries",
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_collections_change"), "collections", ["change"], unique=False
    )
    op.create_index(
        op.f("ix_collections_library_id"), "collections", ["library_id"], unique=False
    )
    op.create_index(
        op.f("ix_collections_parent_id"), "collections", ["parent_id"], unique=False
    )
    op.create_table(
        "imports",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("library_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("blob_sha256", sa.LargeBinary(length=32), nullable=True),
        sa.Column("format", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("done", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("choices", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["blob_sha256"], ["blobs.sha256"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_imports_user_id"), "imports", ["user_id"], unique=False)
    op.create_table(
        "items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("library_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("issued_from", sa.Date(), nullable=True),
        sa.Column("issued_to", sa.Date(), nullable=True),
        sa.Column(
            "file_wanted", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("open_access_tried_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_access_error", sa.Text(), nullable=True),
        sa.Column("published_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("references_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("references_source", sa.String(length=16), nullable=True),
        sa.Column("authors_key", sa.String(length=64), nullable=True),
        sa.Column("authors_linked", sa.String(length=64), nullable=True),
        sa.Column("authors_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.Column("change", sa.BigInteger(), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["library_id"],
            ["libraries.id"],
            ondelete="RESTRICT",
            name="fk_items_library_id_libraries",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_items_change"), "items", ["change"], unique=False)
    op.create_index(op.f("ix_items_changed_at"), "items", ["changed_at"], unique=False)
    op.create_index(
        op.f("ix_items_issued_from"), "items", ["issued_from"], unique=False
    )
    op.create_index(op.f("ix_items_issued_to"), "items", ["issued_to"], unique=False)
    op.create_index(op.f("ix_items_library_id"), "items", ["library_id"], unique=False)
    op.create_index(op.f("ix_items_year"), "items", ["year"], unique=False)
    op.create_table(
        "notes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("library_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(), server_default="", nullable=False),
        sa.Column("title", sa.String(length=300), server_default="", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column("change", sa.BigInteger(), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "text_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notes_change"), "notes", ["change"], unique=False)
    op.create_index(op.f("ix_notes_changed_at"), "notes", ["changed_at"], unique=False)
    op.create_index(op.f("ix_notes_library_id"), "notes", ["library_id"], unique=False)
    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("library_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "change", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["library_id"],
            ["libraries.id"],
            ondelete="CASCADE",
            name="fk_tags_library_id_libraries",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tags_change"), "tags", ["change"], unique=False)
    op.create_index(
        "ix_tags_library_name_lower",
        "tags",
        ["library_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_table(
        "authorships",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("written", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("affiliation", sa.String(), nullable=True),
        sa.Column("orcid", sa.String(length=19), nullable=True),
        sa.Column("openalex_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["authors.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "position"),
    )
    op.create_index(
        op.f("ix_authorships_author_id"), "authorships", ["author_id"], unique=False
    )
    op.create_index(op.f("ix_authorships_key"), "authorships", ["key"], unique=False)
    op.create_table(
        "collection_items",
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("collection_id", "item_id"),
    )
    op.create_index(
        op.f("ix_collection_items_item_id"),
        "collection_items",
        ["item_id"],
        unique=False,
    )
    op.create_table(
        "collection_notes",
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("collection_id", "note_id"),
    )
    op.create_index(
        op.f("ix_collection_notes_note_id"),
        "collection_notes",
        ["note_id"],
        unique=False,
    )
    op.create_table(
        "favourites",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "item_id"),
    )
    op.create_index(
        op.f("ix_favourites_item_id"), "favourites", ["item_id"], unique=False
    )
    op.create_table(
        "import_parts",
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("blob_sha256", sa.LargeBinary(length=32), nullable=True),
        sa.ForeignKeyConstraint(["blob_sha256"], ["blobs.sha256"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["import_id"], ["imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("import_id", "position"),
    )
    op.create_index(
        op.f("ix_import_parts_blob_sha256"),
        "import_parts",
        ["blob_sha256"],
        unique=False,
    )
    op.create_table(
        "item_references",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("authors", sa.String(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("container", sa.String(), nullable=True),
        sa.Column("doi", sa.String(), nullable=True),
        sa.Column("arxiv", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "position"),
    )
    op.create_index(
        op.f("ix_item_references_arxiv"), "item_references", ["arxiv"], unique=False
    )
    op.create_index(
        op.f("ix_item_references_doi"), "item_references", ["doi"], unique=False
    )
    op.create_table(
        "item_tags",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "tag_id"),
    )
    op.create_index(op.f("ix_item_tags_tag_id"), "item_tags", ["tag_id"], unique=False)
    op.create_table(
        "item_views",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "item_id"),
    )
    op.create_index(
        op.f("ix_item_views_item_id"), "item_views", ["item_id"], unique=False
    )
    op.create_table(
        "not_duplicates",
        sa.Column("item_a", sa.Uuid(), nullable=False),
        sa.Column("item_b", sa.Uuid(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_a"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_b"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_a", "item_b"),
    )
    op.create_index(
        op.f("ix_not_duplicates_item_b"), "not_duplicates", ["item_b"], unique=False
    )
    op.create_table(
        "note_chunks",
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("chunk_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunk_sha256"],
            ["chunks.sha256"],
        ),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("note_id", "position"),
    )
    op.create_index(
        op.f("ix_note_chunks_chunk_sha256"),
        "note_chunks",
        ["chunk_sha256"],
        unique=False,
    )
    op.create_table(
        "note_items",
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("note_id", "item_id"),
    )
    op.create_index(
        op.f("ix_note_items_item_id"), "note_items", ["item_id"], unique=False
    )
    op.create_table(
        "note_revisions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("written_by", sa.Uuid(), nullable=True),
        sa.Column("written_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["written_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_note_revisions_note_id"), "note_revisions", ["note_id"], unique=False
    )
    op.create_table(
        "pinned_collections",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "collection_id"),
    )
    op.create_index(
        op.f("ix_pinned_collections_collection_id"),
        "pinned_collections",
        ["collection_id"],
        unique=False,
    )
    op.create_table(
        "versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("csl", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata_source", sa.String(length=32), nullable=False),
        sa.Column(
            "pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_versions_item_id"), "versions", ["item_id"], unique=False)
    op.create_index(
        "ix_versions_one_pinned_per_item",
        "versions",
        ["item_id"],
        unique=True,
        postgresql_where=sa.text("pinned"),
    )
    op.create_table(
        "files",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("blob_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column(
            "text_status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("text_error", sa.String(), nullable=True),
        sa.Column("ocr_status", sa.String(length=16), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["blob_sha256"],
            ["blobs.sha256"],
        ),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_files_blob_sha256"), "files", ["blob_sha256"], unique=False
    )
    op.create_index(op.f("ix_files_ocr_status"), "files", ["ocr_status"], unique=False)
    op.create_index(
        op.f("ix_files_text_status"), "files", ["text_status"], unique=False
    )
    op.create_index(op.f("ix_files_version_id"), "files", ["version_id"], unique=False)
    op.create_table(
        "identifiers",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("scheme", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_identifiers_scheme_value", "identifiers", ["scheme", "value"], unique=False
    )
    op.create_index(
        op.f("ix_identifiers_version_id"), "identifiers", ["version_id"], unique=False
    )
    op.create_table(
        "file_chunks",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("chunk_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column(
            "in_references",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chunk_sha256"],
            ["chunks.sha256"],
        ),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("file_id", "position"),
    )
    op.create_index(
        op.f("ix_file_chunks_chunk_sha256"),
        "file_chunks",
        ["chunk_sha256"],
        unique=False,
    )
    # Users and libraries refer to each other: this one once both exist.
    op.create_foreign_key(
        "fk_users_default_library_id_libraries",
        "users",
        "libraries",
        ["default_library_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("INSERT INTO change_counters (name, value) VALUES ('library', 0)")


def downgrade() -> None:
    op.execute(DROP_PROCRASTINATE)
    op.drop_constraint(
        "fk_users_default_library_id_libraries", "users", type_="foreignkey"
    )
    op.drop_index(op.f("ix_file_chunks_chunk_sha256"), table_name="file_chunks")
    op.drop_table("file_chunks")
    op.drop_index(op.f("ix_identifiers_version_id"), table_name="identifiers")
    op.drop_index("ix_identifiers_scheme_value", table_name="identifiers")
    op.drop_table("identifiers")
    op.drop_index(op.f("ix_files_version_id"), table_name="files")
    op.drop_index(op.f("ix_files_text_status"), table_name="files")
    op.drop_index(op.f("ix_files_ocr_status"), table_name="files")
    op.drop_index(op.f("ix_files_blob_sha256"), table_name="files")
    op.drop_table("files")
    op.drop_index(
        "ix_versions_one_pinned_per_item",
        table_name="versions",
        postgresql_where=sa.text("pinned"),
    )
    op.drop_index(op.f("ix_versions_item_id"), table_name="versions")
    op.drop_table("versions")
    op.drop_index(
        op.f("ix_pinned_collections_collection_id"), table_name="pinned_collections"
    )
    op.drop_table("pinned_collections")
    op.drop_index(op.f("ix_note_revisions_note_id"), table_name="note_revisions")
    op.drop_table("note_revisions")
    op.drop_index(op.f("ix_note_items_item_id"), table_name="note_items")
    op.drop_table("note_items")
    op.drop_index(op.f("ix_note_chunks_chunk_sha256"), table_name="note_chunks")
    op.drop_table("note_chunks")
    op.drop_index(op.f("ix_not_duplicates_item_b"), table_name="not_duplicates")
    op.drop_table("not_duplicates")
    op.drop_index(op.f("ix_item_views_item_id"), table_name="item_views")
    op.drop_table("item_views")
    op.drop_index(op.f("ix_item_tags_tag_id"), table_name="item_tags")
    op.drop_table("item_tags")
    op.drop_index(op.f("ix_item_references_doi"), table_name="item_references")
    op.drop_index(op.f("ix_item_references_arxiv"), table_name="item_references")
    op.drop_table("item_references")
    op.drop_index(op.f("ix_import_parts_blob_sha256"), table_name="import_parts")
    op.drop_table("import_parts")
    op.drop_index(op.f("ix_favourites_item_id"), table_name="favourites")
    op.drop_table("favourites")
    op.drop_index(op.f("ix_collection_notes_note_id"), table_name="collection_notes")
    op.drop_table("collection_notes")
    op.drop_index(op.f("ix_collection_items_item_id"), table_name="collection_items")
    op.drop_table("collection_items")
    op.drop_index(op.f("ix_authorships_key"), table_name="authorships")
    op.drop_index(op.f("ix_authorships_author_id"), table_name="authorships")
    op.drop_table("authorships")
    op.drop_index("ix_tags_library_name_lower", table_name="tags")
    op.drop_index(op.f("ix_tags_change"), table_name="tags")
    op.drop_table("tags")
    op.drop_index(op.f("ix_notes_library_id"), table_name="notes")
    op.drop_index(op.f("ix_notes_changed_at"), table_name="notes")
    op.drop_index(op.f("ix_notes_change"), table_name="notes")
    op.drop_table("notes")
    op.drop_index(op.f("ix_items_year"), table_name="items")
    op.drop_index(op.f("ix_items_library_id"), table_name="items")
    op.drop_index(op.f("ix_items_issued_to"), table_name="items")
    op.drop_index(op.f("ix_items_issued_from"), table_name="items")
    op.drop_index(op.f("ix_items_changed_at"), table_name="items")
    op.drop_index(op.f("ix_items_change"), table_name="items")
    op.drop_table("items")
    op.drop_index(op.f("ix_imports_user_id"), table_name="imports")
    op.drop_table("imports")
    op.drop_index(op.f("ix_collections_parent_id"), table_name="collections")
    op.drop_index(op.f("ix_collections_library_id"), table_name="collections")
    op.drop_index(op.f("ix_collections_change"), table_name="collections")
    op.drop_table("collections")
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("libraries")
    op.drop_index(op.f("ix_access_tokens_user_id"), table_name="access_tokens")
    op.drop_index(op.f("ix_access_tokens_grant_id"), table_name="access_tokens")
    op.drop_table("access_tokens")
    op.drop_table("ocr_pages")
    op.drop_index(op.f("ix_oauth_grants_user_id"), table_name="oauth_grants")
    op.drop_index(op.f("ix_oauth_grants_client_id"), table_name="oauth_grants")
    op.drop_table("oauth_grants")
    op.drop_index(op.f("ix_oauth_codes_user_id"), table_name="oauth_codes")
    op.drop_index(op.f("ix_oauth_codes_client_id"), table_name="oauth_codes")
    op.drop_table("oauth_codes")
    op.drop_index(op.f("ix_login_sessions_user_id"), table_name="login_sessions")
    op.drop_table("login_sessions")
    op.drop_index(op.f("ix_groups_parent_id"), table_name="groups")
    op.drop_table("groups")
    op.drop_index(op.f("ix_exports_user_id"), table_name="exports")
    op.drop_table("exports")
    op.drop_index(op.f("ix_embeddings_model"), table_name="embeddings")
    op.drop_table("embeddings")
    op.drop_table("authors_apart")
    op.drop_table("users")
    op.drop_table("system_settings")
    op.drop_table("oauth_clients")
    op.drop_index("ix_chunks_tsv", table_name="chunks", postgresql_using="gin")
    op.drop_table("chunks")
    op.drop_table("change_counters")
    op.drop_table("blobs")
    op.drop_index(op.f("ix_authors_key"), table_name="authors")
    op.drop_table("authors")
    op.execute("DROP EXTENSION IF EXISTS vector")
