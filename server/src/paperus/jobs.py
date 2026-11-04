"""Background jobs, queued in Postgres with Procrastinate.

The API queues jobs; ``paperus worker`` runs them. A periodic sweep queues
whatever is still pending, so a job that failed to queue is not lost.
"""

import contextlib
import logging
import uuid
from dataclasses import dataclass

from procrastinate import App, Blueprint, JobContext, PsycopgConnector
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import make_url
from sqlalchemy.orm import Session, sessionmaker

from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker
from paperus.processing import pending_files, process_file
from paperus.storage import BlobStore

log = logging.getLogger(__name__)

tasks = Blueprint()


@dataclass
class WorkerContext:
    sessions: sessionmaker[Session]
    blobs: BlobStore


_context: WorkerContext | None = None


def _worker_context() -> WorkerContext:
    if _context is None:
        raise RuntimeError("worker context not set; start with `paperus worker`")
    return _context


@tasks.task(name="extract_text", queue="text", retry=2)
def extract_text(file_id: str) -> None:
    context = _worker_context()
    with context.sessions() as db:
        process_file(db, context.blobs, uuid.UUID(file_id))


@tasks.periodic(cron="*/5 * * * *")
@tasks.task(
    name="queue_pending_files", queue="text", queueing_lock="sweep", pass_context=True
)
def queue_pending_files(job: JobContext, timestamp: int) -> None:
    context = _worker_context()
    with context.sessions() as db:
        for file_id in pending_files(db):
            queue_text_extraction(job.app, file_id)


def queue_text_extraction(app: App, file_id: uuid.UUID) -> None:
    """Queue extraction for a file, unless it is queued already.

    By task name through ``app``: the blueprint's task objects are shared
    between apps (e.g. in tests).
    """
    task = app.configure_task("paperus:extract_text", queueing_lock=str(file_id))
    with contextlib.suppress(AlreadyEnqueued):
        task.defer(file_id=str(file_id))


def conninfo(database_url: str) -> str:
    """Procrastinate wants a plain libpq URL, without SQLAlchemy's driver."""
    url = make_url(database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def make_job_app(settings: Settings) -> App:
    app = App(connector=PsycopgConnector(conninfo=conninfo(settings.database_url)))
    app.add_tasks_from(tasks, namespace="paperus")
    return app


def run_worker(settings: Settings) -> None:
    global _context
    _context = WorkerContext(
        sessions=make_sessionmaker(make_engine(settings.database_url)),
        blobs=BlobStore(settings.storage_path),
    )
    app = make_job_app(settings)
    with app.open():
        app.run_worker(queues=["text"])
