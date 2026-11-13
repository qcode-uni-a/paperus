"""The migrations give the schema the models describe."""

import uuid
from datetime import UTC, datetime

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from paperus.models import Base, Chunk, Item, ItemChunk, User, Version
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


def test_0003_gives_papers_the_abstract_of_their_details(
    logged_in: TestClient, db: Session, database_url: str
) -> None:
    """An installation of 0.0.18 updated: a paper whose abstract came with
    its details (0002 took only those found for it) found by it too."""
    response = logged_in.post(
        "/api/items",
        json={
            "metadata": {
                "title": "Glacier retreat",
                "abstract": "<jats:p>Ice loss in the Alps.</jats:p>",
            }
        },
    )
    item_id = uuid.UUID(response.json()["id"])
    title_only = db.get(ItemChunk, item_id)
    assert title_only is not None
    db.merge(Chunk(sha256=b"\0" * 32, text="Glacier retreat"))
    title_only.chunk_sha256 = b"\0" * 32
    db.commit()
    db.close()
    config = Config(SERVER_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "0002")
    command.upgrade(config, "head")

    text = db.scalar(
        select(Chunk.text)
        .join(ItemChunk, ItemChunk.chunk_sha256 == Chunk.sha256)
        .where(ItemChunk.item_id == item_id)
    )
    assert text == "Glacier retreat\n\nIce loss in the Alps."


def test_0012_gives_papers_their_first_author_and_journal(
    logged_in: TestClient, db: Session, database_url: str
) -> None:
    """An installation of 0.0.28 updated: its papers sorted by first author
    and journal, as the preferred version and the paper's edits have them."""

    def add(metadata: dict[str, object], kind: str = "preprint") -> str:
        response = logged_in.post(
            "/api/items", json={"metadata": metadata, "kind": kind}
        )
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    preprint = add(
        {"title": "Spin qubits", "author": [{"family": "Early", "given": "A."}]}
    )
    published = logged_in.post(
        f"/api/items/{preprint}/versions",
        json={
            "kind": "published",
            "metadata": {
                "title": "Spin qubits",
                "author": [{"literal": ""}, {"family": "Benito", "given": "Mónica"}],
                "container-title": ["Physical Review B"],
            },
        },
    )
    assert published.status_code == 201, published.text
    edited = add({"title": "Edited", "author": [{"family": "Wrong"}]})
    item = logged_in.get(f"/api/items/{edited}")
    response = logged_in.put(
        f"/api/items/{edited}/overrides",
        json={"author": [{"literal": "The Lab"}], "container-title": " Notes "},
        headers={"If-Match": item.headers["ETag"]},
    )
    assert response.status_code == 200, response.text
    bare = add({"title": "Bare"})
    db.close()
    config = Config(SERVER_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "0011")
    command.upgrade(config, "head")

    rows = {
        str(row.id): (row.first_author, row.journal)
        for row in db.execute(select(Item.id, Item.first_author, Item.journal))
    }
    assert rows[preprint] == ("Benito, Mónica", "Physical Review B")
    assert rows[edited] == ("The Lab", "Notes")
    assert rows[bare] == (None, None)


def test_0014_labels_preprints_by_their_pdfs_arxiv_version(
    logged_in: TestClient, db: Session, database_url: str
) -> None:
    """An installation of 0.1.0 updated: a preprint whose PDF arXiv named
    with its version ("2401.12345v2.pdf") is that version ("v2")."""
    made = logged_in.post(
        "/api/items",
        json={
            "metadata": {"title": "Spin qubits"},
            "identifiers": [{"scheme": "arxiv", "value": "2401.12345"}],
        },
    )
    item_id = made.json()["id"]
    logged_in.post(
        f"/api/items/{item_id}/files",
        files={
            "upload": ("2401.12345v2.pdf", b"%PDF-1.7\nx\n%%EOF\n", "application/pdf")
        },
    )
    version = db.scalars(select(Version).where(Version.item_id == item_id)).one()
    version.label = None  # as before 0.1.1
    db.commit()
    db.close()
    config = Config(SERVER_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "0013")
    command.upgrade(config, "head")

    assert (
        db.scalars(select(Version.label).where(Version.item_id == item_id)).one()
        == "v2"
    )


def test_0015_moves_waiting_lookups_to_their_own_queue(
    db: Session, database_url: str
) -> None:
    """An installation of 0.1.0 updated with lookups waiting behind files to
    read: they move to "lookup"; the files stay, as do lookups running."""
    config = Config(SERVER_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "0014")
    rows = [
        ("paperus:find_item_references", "todo"),
        ("paperus:fetch_open_access", "doing"),
        ("paperus:extract_text", "todo"),
    ]
    ids = [
        db.execute(
            text(
                "INSERT INTO procrastinate_jobs (queue_name, task_name, status,"
                " args) VALUES ('text', :task, :status, '{}') RETURNING id"
            ),
            {"task": task, "status": status},
        ).scalar_one()
        for task, status in rows
    ]
    db.commit()
    db.close()
    command.upgrade(config, "head")

    queues = [
        db.execute(
            text("SELECT queue_name FROM procrastinate_jobs WHERE id = :id"),
            {"id": job_id},
        ).scalar_one()
        for job_id in ids
    ]
    assert queues == ["lookup", "text", "text"]
    db.execute(
        text("DELETE FROM procrastinate_jobs WHERE id = ANY(:ids)"), {"ids": ids}
    )
    db.commit()


def test_0016_last_active_from_logins_and_tokens(
    logged_in: TestClient, db: Session, database_url: str
) -> None:
    """Updated: "last active" starts as the later of the last login and the
    last use of one's access tokens; using paperus keeps it current."""
    made = logged_in.post(
        "/api/me/tokens", json={"name": "Script", "scopes": ["papers.read"]}
    ).json()
    config = Config(SERVER_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    db.close()
    command.downgrade(config, "0015")
    used = datetime(2026, 11, 1, tzinfo=UTC)
    db.execute(
        text("UPDATE users SET last_login_at = :at - interval '3 days'"),
        {"at": used},
    )
    db.execute(text("UPDATE access_tokens SET last_used_at = :at"), {"at": used})
    db.commit()
    db.close()
    command.upgrade(config, "head")

    [active] = db.scalars(select(User.last_active_at)).all()
    assert active == used
    db.close()
    # Using it with the token: now.
    logged_in.get("/api/items", headers={"Authorization": f"Bearer {made['token']}"})
    [active] = db.scalars(select(User.last_active_at)).all()
    assert active is not None and active > used
