"""Data migrations that need checking with data in place."""

from datetime import date

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import SERVER_DIR
from tests.people import Person


def test_installations_using_bge_m3_keep_it(
    engine: Engine, db: Session, database_url: str
) -> None:
    config = Config(SERVER_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "0014")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM system_settings"))
        connection.execute(
            text("INSERT INTO chunks (sha256, text) VALUES ('\\x00', 'rain')")
        )
        connection.execute(
            text(
                "INSERT INTO embeddings (chunk_sha256, model, embedding)"
                " VALUES ('\\x00', 'bge-m3', '[1,0]')"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        value = connection.scalar(
            text("SELECT value FROM system_settings WHERE key = 'config'")
        )
    assert value == {"embedding_model": "bge-m3"}
    # Without bge-m3 vectors (a new installation): nothing saved, the
    # default applies.
    command.downgrade(config, "0014")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM system_settings"))
        connection.execute(text("DELETE FROM embeddings"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM system_settings")) == 0


def test_papers_get_their_publication_days(
    client: TestClient, engine: Engine, db: Session, database_url: str
) -> None:
    """Migration 0028 fills in the days each paper's date stands for, from
    the version whose details are shown (published before preprint) and
    the paper's own edits."""
    ada = Person(client, db, "ada")

    def add(title: str, *parts: list[int]) -> str:
        metadata: dict[str, object] = {"title": title}
        if parts:
            metadata["issued"] = {"date-parts": list(parts)}
        response = ada.post("/api/items", json={"metadata": metadata})
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    day = add("A day", [2024, 3, 15])
    versions = add("Preprint first", [2022, 5])
    response = ada.post(
        f"/api/items/{versions}/versions",
        json={"metadata": {"title": "Published", "issued": {"date-parts": [[2024]]}},
              "kind": "published"},
    )  # fmt: skip
    assert response.status_code == 201, response.text
    edited = add("Edited", [1999])
    etag = ada.get(f"/api/items/{edited}").headers["ETag"]
    response = client.put(
        f"/api/items/{edited}/overrides",
        json={"issued": {"date-parts": [[2020, 2]]}},
        headers={**ada.headers, "If-Match": etag},
    )
    assert response.status_code == 200, response.text
    undated = add("Undated")

    config = Config(SERVER_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "0027")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        found = {
            str(row.id): (row.issued_from, row.issued_to)
            for row in connection.execute(
                text("SELECT id, issued_from, issued_to FROM items")
            )
        }
    assert found[day] == (date(2024, 3, 15), date(2024, 3, 15))
    assert found[versions] == (date(2024, 1, 1), date(2024, 12, 31))
    assert found[edited] == (date(2020, 2, 1), date(2020, 2, 29))
    assert found[undated] == (None, None)
