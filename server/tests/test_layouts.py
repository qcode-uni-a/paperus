"""Fluent mode's page layouts stored per file content: made in the worker,
given to the viewer, made again after the layout code changed."""

from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from paperus import jobs, layouts, page_layout, pdf
from paperus.config import Settings
from paperus.db import make_sessionmaker
from paperus.jobs import WorkerContext
from paperus.models import File, PageLayouts
from paperus.storage import BlobStore
from tests.pdfs import make_pdf
from tests.test_files import add_item, upload


@pytest.fixture
def job_app(monkeypatch: pytest.MonkeyPatch) -> App:
    """Jobs in memory, runnable by their queued names (as in test_worker)."""
    app = App(connector=InMemoryConnector())
    for task in set(jobs.tasks.tasks.values()):
        name = f"paperus:{task.name.rsplit(':', 1)[-1]}"
        monkeypatch.setattr(task, "name", name)
        monkeypatch.setattr(task, "blueprint", app)
        app.tasks[name] = task
    return app


@pytest.fixture
def worker(
    engine: Engine,
    settings: Settings,
    blobs: BlobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    monkeypatch.setattr(
        jobs,
        "_context",
        WorkerContext(
            engine=engine,
            sessions=make_sessionmaker(engine),
            blobs=blobs,
            http=cast(Any, None),
            ml=cast(Any, None),
            settings=settings,
        ),
    )
    yield


def queued(app: App) -> list[tuple[str, int, dict[str, Any]]]:
    assert isinstance(app.connector, InMemoryConnector)
    return [
        (job["task_name"].removeprefix("paperus:"), job["priority"], job["args"])
        for job in app.connector.jobs.values()
        if job["status"] == "todo"
    ]


def run(app: App) -> None:
    app.run_worker(
        queues=["text", "layout"],
        wait=False,
        install_signal_handlers=False,
        listen_notify=False,
    )


PAPER = make_pdf(
    [
        ["On reading in columns", "A. Tester", "", "Abstract. " + "words " * 12],
        ["Results", "The effect is real and measurable."],
    ]
)


def test_made_when_asked_and_given(
    logged_in: TestClient, job_app: App, worker: None, db: Session
) -> None:
    file = upload(logged_in, add_item(logged_in, "A"), PAPER)
    url = f"/api/files/{file['id']}/layout"
    asked = logged_in.get(url)
    assert asked.status_code == 202
    assert asked.headers["retry-after"] == "3"
    # First in line, once however often it is asked.
    logged_in.get(url)
    layout_jobs = [job for job in queued(job_app) if job[0] == "page_layout"]
    assert layout_jobs == [
        ("page_layout", jobs.LAYOUT_ASKED, {"sha256": file["sha256"]})
    ]

    run(job_app)
    given = logged_in.get(url)
    assert given.status_code == 200
    body = given.json()
    assert body["version"] == page_layout.VERSION
    assert body["current"] is True
    assert len(body["pages"]) == 2
    first = body["pages"][0]
    assert first["width"] == 612
    assert first["columns"] is False
    assert first["pieces"]
    assert {"x", "y", "width", "height", "wide", "span"} <= first["pieces"][0].keys()


def test_older_ones_given_while_made_again(
    logged_in: TestClient, job_app: App, worker: None, db: Session
) -> None:
    file = upload(logged_in, add_item(logged_in, "A"), PAPER)
    sha256 = bytes.fromhex(str(file["sha256"]))
    layouts.make(db, jobs._worker_context().blobs, sha256)
    db.execute(update(PageLayouts).values(version=page_layout.VERSION - 1))
    db.commit()
    assert layouts.outdated(db) == [sha256]

    response = logged_in.get(f"/api/files/{file['id']}/layout")
    assert response.status_code == 200
    assert response.json()["current"] is False
    run(job_app)
    db.expire_all()
    assert db.scalar(select(PageLayouts.version)) == page_layout.VERSION
    assert layouts.outdated(db) == []
    assert logged_in.get(f"/api/files/{file['id']}/layout").json()["current"] is True


def test_the_sweep_queues_what_is_missing_last(
    logged_in: TestClient, job_app: App, worker: None, db: Session
) -> None:
    file = upload(logged_in, add_item(logged_in, "A"), PAPER)
    # A file in the trash, and one that is no PDF: none.
    other = upload(logged_in, add_item(logged_in, "B"), make_pdf([["Other"]]))
    db.execute(
        update(File).where(File.id == other["id"]).values(deleted_at=File.created_at)
    )
    upload(
        logged_in, add_item(logged_in, "C"), b"plain words", "notes.txt", "text/plain"
    )
    db.commit()
    assert isinstance(job_app.connector, InMemoryConnector)
    job_app.connector.jobs.clear()

    jobs.queue_outdated_layouts(cast(Any, type("Context", (), {"app": job_app})), 0)
    assert queued(job_app) == [
        ("page_layout", jobs.LAYOUT_LATER, {"sha256": file["sha256"]})
    ]


def test_made_once_a_pdf_is_read(
    logged_in: TestClient, job_app: App, worker: None, db: Session
) -> None:
    file = upload(logged_in, add_item(logged_in, "A"), PAPER)
    run(job_app)
    made = db.get(PageLayouts, bytes.fromhex(str(file["sha256"])))
    assert made is not None
    assert len(made.pages) == 2


def test_none_for_what_is_no_pdf_or_cannot_be_read(
    logged_in: TestClient,
    job_app: App,
    worker: None,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = upload(logged_in, add_item(logged_in, "A"), b"words", "a.txt", "text/plain")
    assert logged_in.get(f"/api/files/{text['id']}/layout").status_code == 404

    def broken(path: object) -> list[Any]:
        raise pdf.PdfError("damaged")

    monkeypatch.setattr(pdf, "layouts", broken)
    file = upload(logged_in, add_item(logged_in, "B"), PAPER)
    run(job_app)
    response = logged_in.get(f"/api/files/{file['id']}/layout")
    assert response.status_code == 404
    # Not tried again until the code changes.
    assert db.scalar(select(PageLayouts.pages)) == []
    assert layouts.outdated(db) == []
