"""The migrations give the schema the models describe."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine

from paperus.models import Base


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Procrastinate's tables are its own (as in migrations/env.py)."""
    return not (name or "").startswith("procrastinate")


def test_the_models_match_the_migrations(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"include_name": include_name, "compare_type": True}
        )
        assert compare_metadata(context, Base.metadata) == []
