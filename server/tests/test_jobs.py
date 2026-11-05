"""The worker: jobs at once per queue, and the nightly jobs' hour."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from paperus import auth, integrity, jobs
from paperus.backup import due
from paperus.config import Settings
from paperus.db import make_sessionmaker
from paperus.jobs import WorkerContext, job_limits, run_workers
from paperus.models import Item, LoginSession, SystemSetting
from paperus.storage import BlobStore
from paperus.system import SystemConfig, load_config, save_config
from tests.people import Person


class FakeApp:
    """Records the workers started; each runs until cancelled."""

    def __init__(self) -> None:
        self.started: list[tuple[str, int]] = []
        self.cancelled: list[tuple[str, int]] = []

    @contextlib.asynccontextmanager
    async def open_async(self) -> AsyncGenerator[None]:
        yield

    async def run_worker_async(self, **options: Any) -> None:  # noqa: ANN401
        worker = (options["queues"][0], options["concurrency"])
        self.started.append(worker)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.append(worker)
            raise


def test_job_limits() -> None:
    config = SystemConfig(embedding_model="m", jobs_text=4, jobs_ml=2)
    assert job_limits(config) == {"text": 4, "ml": 2, "import": 1, "backup": 1}


def test_workers_follow_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "LIMITS_SECONDS", 0.01)
    app = FakeApp()
    rounds = iter(
        [
            {"text": 2, "backup": 1},
            {"text": 2, "backup": 1},
            {"text": 4, "backup": 1},
        ]
    )

    async def main() -> None:
        stop = asyncio.Event()

        def limits() -> dict[str, int]:
            try:
                return next(rounds)
            except StopIteration:
                stop.set()
                return {"text": 4, "backup": 1}

        await run_workers(cast(App, app), limits, stop)

    asyncio.run(main())
    assert app.started == [("text", 2), ("backup", 1), ("text", 4)]
    # The replaced worker first, then all at the end.
    assert app.cancelled[0] == ("text", 2)
    assert sorted(app.cancelled[1:]) == [("backup", 1), ("text", 4)]


def test_weekly_on_a_chosen_day() -> None:
    sunday_2 = datetime(2026, 11, 8, 2, tzinfo=UTC)
    assert due(None, "weekly", 2, sunday_2, weekday=6)
    assert not due(None, "weekly", 2, sunday_2)  # backups: Mondays
    assert due(sunday_2 - timedelta(days=1), "daily", 2, sunday_2, weekday=6)


@pytest.fixture
def worker(
    engine: Engine,
    settings: Settings,
    blobs: BlobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    context = WorkerContext(
        engine=engine,
        sessions=make_sessionmaker(engine),
        blobs=blobs,
        http=cast(Any, None),
        ml=cast(Any, None),
        settings=settings,
    )
    monkeypatch.setattr(jobs, "_context", context)
    yield


def _at(hour: int) -> int:
    return int(datetime(2026, 11, 8, hour, 30, tzinfo=UTC).timestamp())


def test_trash_emptied_at_the_night_hour(
    client: TestClient, db: Session, settings: Settings, worker: None
) -> None:
    ada = Person(client, db, "ada")
    old = ada.add("Old")
    ada.delete(f"/api/items/{old['id']}")
    long_ago = datetime.now(UTC) - timedelta(days=40)
    db.execute(update(Item).values(deleted_at=long_ago))
    config = load_config(db, settings)
    config.trash_days = 30
    config.night_hour = 3
    save_config(db, config)
    db.commit()

    jobs.empty_old_trash(_at(2))
    assert db.scalar(select(Item.id)) is not None
    jobs.empty_old_trash(_at(3))
    db.expire_all()
    assert db.scalar(select(Item.id)) is None


def test_integrity_on_its_schedule(
    db: Session, settings: Settings, worker: None
) -> None:
    config = load_config(db, settings)
    config.night_hour = 4
    config.integrity_schedule = "daily"
    save_config(db, config)
    db.commit()

    jobs.scheduled_integrity(_at(3))
    assert integrity.last_report(db) is None
    jobs.scheduled_integrity(_at(4))
    assert integrity.last_report(db) is not None

    config.integrity_schedule = "off"
    save_config(db, config)
    db.commit()
    db.execute(delete(SystemSetting).where(SystemSetting.key == integrity.KEY))
    db.commit()
    jobs.scheduled_integrity(_at(4))
    assert integrity.last_report(db) is None


def test_expired_sessions_removed(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    assert auth.remove_expired_sessions(db) == 0
    db.execute(update(LoginSession).values(expires_at=datetime.now(UTC) - timedelta(1)))
    assert auth.remove_expired_sessions(db) == 1
    db.commit()
    assert ada.get("/api/auth/me").status_code == 401


def test_tidy(job_app: App, worker: None, db: Session, settings: Settings) -> None:
    """Runs against Procrastinate (here its in-memory stand-in), at the
    night hour and outside it."""
    config = load_config(db, settings)
    config.night_hour = 3
    save_config(db, config)
    db.commit()
    context = cast(Any, type("Context", (), {"app": job_app}))
    asyncio.run(jobs.tidy(context, _at(2)))
    asyncio.run(jobs.tidy(context, _at(3)))
