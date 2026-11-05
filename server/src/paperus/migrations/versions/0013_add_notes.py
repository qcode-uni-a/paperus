"""Add notes: Markdown with an owner, linked to items and collections

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-05 15:46:36.244933
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index(op.f("ix_note_revisions_note_id"), table_name="note_revisions")
    op.drop_table("note_revisions")
    op.drop_index(op.f("ix_note_items_item_id"), table_name="note_items")
    op.drop_table("note_items")
    op.drop_index(op.f("ix_note_chunks_chunk_sha256"), table_name="note_chunks")
    op.drop_table("note_chunks")
    op.drop_index(op.f("ix_collection_notes_note_id"), table_name="collection_notes")
    op.drop_table("collection_notes")
    op.drop_index(op.f("ix_notes_library_id"), table_name="notes")
    op.drop_index(op.f("ix_notes_changed_at"), table_name="notes")
    op.drop_index(op.f("ix_notes_change"), table_name="notes")
    op.drop_table("notes")
