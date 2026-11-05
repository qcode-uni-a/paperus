"""Add groups, memberships and libraries

Every person gets a private library. Items, tags and collections made before
groups existed move into a first group, "Shared library", with every
existing user as a member (administrators as its admins), so nobody loses
sight of anything.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05 18:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"


def _record_columns() -> list[sa.Column]:
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
        "groups",
        *_record_columns(),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_id"], ["groups.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_groups_parent_id"), "groups", ["parent_id"])
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
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"])
    op.create_table(
        "libraries",
        *_record_columns(),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (group_id IS NULL)",
            name=op.f("ck_libraries_one_owner"),
        ),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id"),
        sa.UniqueConstraint("user_id"),
    )
    op.add_column("users", sa.Column("default_library_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_default_library_id_libraries"),
        "users",
        "libraries",
        ["default_library_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for table in ("items", "tags", "collections"):
        op.add_column(table, sa.Column("library_id", sa.Uuid(), nullable=True))

    # A private library for everyone.
    op.execute("INSERT INTO libraries (user_id) SELECT id FROM users")
    # Everything made so far goes into a first shared group.
    op.execute("""
        DO $$
        DECLARE shared_group uuid; shared_library uuid;
        BEGIN
            IF EXISTS (SELECT 1 FROM items) OR EXISTS (SELECT 1 FROM tags)
               OR EXISTS (SELECT 1 FROM collections) THEN
                INSERT INTO groups (name, description)
                VALUES ('Shared library', 'Everything added before groups existed.')
                RETURNING id INTO shared_group;
                INSERT INTO libraries (group_id) VALUES (shared_group)
                RETURNING id INTO shared_library;
                INSERT INTO memberships (group_id, user_id, role)
                SELECT shared_group, id,
                       CASE WHEN is_admin THEN 'admin' ELSE 'member' END
                FROM users;
                UPDATE items SET library_id = shared_library;
                UPDATE tags SET library_id = shared_library;
                UPDATE collections SET library_id = shared_library;
                UPDATE users SET default_library_id = shared_library;
            END IF;
        END $$;
    """)
    op.execute("""
        UPDATE users SET default_library_id = libraries.id
        FROM libraries
        WHERE libraries.user_id = users.id AND users.default_library_id IS NULL
    """)

    for table, ondelete in (
        ("items", "RESTRICT"),
        ("tags", "CASCADE"),
        ("collections", "CASCADE"),
    ):
        op.alter_column(table, "library_id", nullable=False)
        op.create_foreign_key(
            op.f(f"fk_{table}_library_id_libraries"),
            table,
            "libraries",
            ["library_id"],
            ["id"],
            ondelete=ondelete,
        )
    op.create_index(op.f("ix_items_library_id"), "items", ["library_id"])
    op.create_index(op.f("ix_collections_library_id"), "collections", ["library_id"])
    op.drop_index("ix_tags_name_lower", table_name="tags")
    op.create_index(
        "ix_tags_library_name_lower",
        "tags",
        ["library_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.drop_constraint("identifiers_scheme_value_key", "identifiers", type_="unique")
    op.create_index("ix_identifiers_scheme_value", "identifiers", ["scheme", "value"])


def downgrade() -> None:
    raise NotImplementedError("groups cannot be removed without losing data")
