"""The migrations give the schema the models describe."""

import uuid

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from paperus.models import Base, Chunk, Item, ItemChunk
from tests.conftest import SERVER_DIR


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Procrastinate's tables are its own (as in migrations/env.py)."""
    return not (name or "").startswith("procrastinate")


def test_the_models_match_the_migrations(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"include_name": include_name, "compare_type": True}
        )
        assert compare_metadata(context, Base.metadata) == []


def test_0002_gives_papers_there_are_their_details(
    logged_in: TestClient, db: Session, database_url: str
) -> None:
    """An installation of 0.0.17 updated: its papers found by their title
    and abstract too."""
    ids = [
        uuid.UUID(
            logged_in.post("/api/items", json={"metadata": {"title": title}}).json()[
                "id"
            ]
        )
        for title in ("Rainfall records", "Snowfall records")
    ]
    item = db.get(Item, ids[1])
    assert item is not None
    item.abstract = "Daily depths."
    db.commit()
    db.close()
    config = Config(SERVER_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "0001")
    command.upgrade(config, "head")

    texts = dict(
        db.execute(
            select(ItemChunk.item_id, Chunk.text).join(
                Chunk, Chunk.sha256 == ItemChunk.chunk_sha256
            )
        ).all()
    )
    assert [texts[i] for i in ids] == [
        "Rainfall records",
        "Snowfall records\n\nDaily depths.",
    ]
