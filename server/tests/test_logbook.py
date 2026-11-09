"""The log in the database (``paperus.logbook``, Administration → Logs)."""

import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from paperus import logbook
from paperus.models import LogEntry
from tests.people import Person


def wait_for(db: Session, count: int) -> list[LogEntry]:
    """The entries, once the handler's thread has written ``count``."""
    for _ in range(100):
        entries = list(db.scalars(select(LogEntry).order_by(LogEntry.id)))
        db.rollback()
        if len(entries) >= count:
            return entries
        time.sleep(0.05)
    raise AssertionError(f"{count} log entries expected, found {len(entries)}")


@pytest.fixture
def installed(engine: Engine) -> Iterator[logbook.DatabaseHandler]:
    logbook.install(engine, "worker")
    logbook.install(engine, "server")  # once per process: still the worker's
    handler = logbook._installed
    assert handler is not None
    yield handler
    logging.getLogger().removeHandler(handler)
    logbook._installed = None


def test_paperus_at_its_level_others_from_warnings(
    installed: logbook.DatabaseHandler, db: Session
) -> None:
    ours = logging.getLogger("paperus.testing")
    ours.setLevel(logging.INFO)
    ours.debug("not at this level")
    ours.info("saved %d files", 3)
    logging.getLogger("somelibrary").info("chatter")
    logging.getLogger("somelibrary").warning("trouble")
    try:
        raise ValueError("bad input")
    except ValueError:
        ours.exception("job failed")

    entries = wait_for(db, 3)
    assert [(e.source, e.level, e.logger, e.message[:16]) for e in entries] == [
        ("worker", "info", "paperus.testing", "saved 3 files"),
        ("worker", "warning", "somelibrary", "trouble"),
        ("worker", "error", "paperus.testing", "job failed\nTrace"),
    ]
    assert "ValueError: bad input" in entries[2].message


def test_the_database_away_loses_entries_quietly(db: Session) -> None:
    class Away:
        def begin(self) -> None:
            raise OSError("no database")

    handler = logbook.DatabaseHandler(cast("Engine", Away()), "server")
    record = logging.LogRecord("paperus.x", logging.INFO, "", 0, "lost", None, None)
    handler.emit(record)
    # A message that cannot be formatted is the handler's error, as usual.
    broken = logging.LogRecord("paperus.x", logging.INFO, "", 0, "%d", ("x",), None)
    handler.emit(broken)
    time.sleep(0.2)
    assert db.scalar(select(func.count()).select_from(LogEntry)) == 0


def test_prune(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    for days in (20, 15, 3, 2, 1, 0):
        db.add(
            LogEntry(
                at=now - timedelta(days=days),
                level="info",
                source="server",
                logger="paperus",
                message=f"{days} days ago",
            )
        )
    db.commit()
    monkeypatch.setattr(logbook, "MOST", 3)
    assert logbook.prune(db, now) == 3  # two too old, one too many
    db.commit()
    kept = db.scalars(select(LogEntry.message).order_by(LogEntry.id)).all()
    assert kept == ["2 days ago", "1 days ago", "0 days ago"]


def test_administrators_read_the_log(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    for i, (level, source) in enumerate(
        [
            ("debug", "server"),
            ("info", "worker"),
            ("warning", "server"),
            ("error", "worker"),
        ]
    ):
        db.add(
            LogEntry(level=level, source=source, logger="paperus", message=f"entry {i}")
        )
    db.commit()

    def messages(**params: str | list[str]) -> list[str]:
        page = root.get("/api/admin/logs", params=params).json()
        return [e["message"] for e in page["entries"]]

    assert messages() == ["entry 3", "entry 2", "entry 1"]  # info and up
    assert messages(level="debug") == ["entry 3", "entry 2", "entry 1", "entry 0"]
    assert messages(level="warning", source=["server"]) == ["entry 2"]
    assert messages(level="debug", q="ENTRY 1") == ["entry 1"]
    page = root.get("/api/admin/logs", params={"limit": "2"}).json()
    assert page["more"] is True
    before = str(page["entries"][-1]["id"])
    assert messages(before=before) == ["entry 1"]

    assert ada.get("/api/admin/logs").status_code == 403


def test_the_extension_reports(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    extension = ada.post(
        "/api/me/tokens",
        json={"name": "Browser extension", "scopes": ["papers.read", "papers.write"]},
    ).json()["token"]
    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    response = client.post(
        "/api/logs",
        headers={"Authorization": f"Bearer {extension}"},
        json={
            "version": "0.0.19",
            "entries": [
                {
                    "level": "warning",
                    "message": "No access: the publisher asks for a login.",
                    "context": {"page": "https://journals.aps.org/prb/abstract/x"},
                },
                {"level": "error", "message": "From the future", "at": later},
            ],
        },
    )
    assert response.status_code == 204, response.text

    entries = root.get("/api/admin/logs", params={"source": ["extension"]}).json()
    first = entries["entries"][1]
    assert (first["level"], first["logger"], first["username"]) == (
        "warning",
        "extension 0.0.19",
        "ada",
    )
    assert first["context"] == {"page": "https://journals.aps.org/prb/abstract/x"}
    # A clock ahead is not believed.
    assert entries["entries"][0]["at"] <= datetime.now(UTC).isoformat()

    reader = ada.post(
        "/api/me/tokens", json={"name": "Assistant", "scopes": ["papers.read"]}
    ).json()["token"]
    response = client.post(
        "/api/logs",
        headers={"Authorization": f"Bearer {reader}"},
        json={"version": "1", "entries": [{"level": "info", "message": "x"}]},
    )
    assert response.status_code == 403
