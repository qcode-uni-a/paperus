"""Background jobs, queued in Postgres with Procrastinate.

The API queues jobs; ``paperus worker`` runs them. A periodic sweep queues
whatever is still pending, so a job that failed to queue is not lost.
"""

import contextlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx2
from procrastinate import App, Blueprint, JobContext, PsycopgConnector, RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from paperus import integrity, trash
from paperus.backup import create_backup, due, last_backup_time, prune
from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker
from paperus.embedding import (
    embed_file,
    embed_note,
    files_missing_embeddings,
    notes_missing_embeddings,
)
from paperus.importing.run import run_import
from paperus.metadata import make_http_client
from paperus.ml import MLClient, MLUnavailable, make_ml_client
from paperus.models import Import, ImportStatus
from paperus.processing import pending_files, process_file
from paperus.storage import BlobStore, make_blob_store
from paperus.system import (
    SystemConfig,
    apply,
    load_backup_config,
    load_config,
    max_upload_bytes,
)

log = logging.getLogger(__name__)

tasks = Blueprint()


@dataclass
class WorkerContext:
    engine: Engine
    sessions: sessionmaker[Session]
    blobs: BlobStore
    http: httpx2.Client
    ml: MLClient
    settings: Settings


_context: WorkerContext | None = None


def _worker_context() -> WorkerContext:
    if _context is None:
        raise RuntimeError("worker context not set; start with `paperus worker`")
    return _context


@tasks.task(name="extract_text", queue="text", retry=2, pass_context=True)
def extract_text(job: JobContext, file_id: str) -> None:
    context = _worker_context()
    with context.sessions() as db:
        process_file(db, context.blobs, uuid.UUID(file_id), context.http)
    queue_embedding(job.app, uuid.UUID(file_id))


# The ML service may be down or busy (model download): retry for about half
# an hour with growing pauses; the periodic sweep catches the rest.
@tasks.task(
    name="embed_file",
    queue="ml",
    retry=RetryStrategy(
        max_attempts=10, exponential_wait=2, retry_exceptions={MLUnavailable}
    ),
)
def embed(file_id: str) -> None:
    context = _worker_context()
    with context.sessions() as db:
        model = load_config(db, context.settings).embedding_model
        count = embed_file(db, context.ml, model, uuid.UUID(file_id))
    log.info("embedded %d chunks of file %s", count, file_id)


@tasks.task(
    name="embed_note",
    queue="ml",
    retry=RetryStrategy(
        max_attempts=10, exponential_wait=2, retry_exceptions={MLUnavailable}
    ),
)
def embed_a_note(note_id: str) -> None:
    context = _worker_context()
    with context.sessions() as db:
        model = load_config(db, context.settings).embedding_model
        count = embed_note(db, context.ml, model, uuid.UUID(note_id))
    log.info("embedded %d chunks of note %s", count, note_id)


@tasks.periodic(cron="*/10 * * * *")
@tasks.task(
    name="queue_missing_embeddings",
    queue="ml",
    queueing_lock="embedding-sweep",
    pass_context=True,
)
def queue_missing_embeddings(job: JobContext, timestamp: int) -> None:
    """Also re-embeds the library after the embedding model changed."""
    context = _worker_context()
    with context.sessions() as db:
        model = load_config(db, context.settings).embedding_model
        for file_id in files_missing_embeddings(db, model):
            queue_embedding(job.app, file_id)
        for note_id in notes_missing_embeddings(db, model):
            queue_note_embedding(job.app, note_id)


def queue_embedding_sweep(app: App) -> None:
    """Look for missing embeddings now (e.g. after the model changed)."""
    task = app.configure_task(
        "paperus:queue_missing_embeddings", queueing_lock="embedding-sweep"
    )
    with contextlib.suppress(AlreadyEnqueued):
        task.defer(timestamp=0)


def queue_text_sweep(app: App) -> None:
    """Look for files whose text is still pending now."""
    task = app.configure_task("paperus:queue_pending_files", queueing_lock="sweep")
    with contextlib.suppress(AlreadyEnqueued):
        task.defer(timestamp=0)


def queue_note_embedding(app: App, note_id: uuid.UUID) -> None:
    task = app.configure_task(
        "paperus:embed_note", queueing_lock=f"embed-note-{note_id}"
    )
    with contextlib.suppress(AlreadyEnqueued):
        task.defer(note_id=str(note_id))


def queue_embedding(app: App, file_id: uuid.UUID) -> None:
    task = app.configure_task("paperus:embed_file", queueing_lock=f"embed-{file_id}")
    with contextlib.suppress(AlreadyEnqueued):
        task.defer(file_id=str(file_id))


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
    engine = make_engine(settings.database_url)
    _context = WorkerContext(
        engine=engine,
        sessions=make_sessionmaker(engine),
        blobs=make_blob_store(settings),
        http=make_http_client(settings),
        ml=make_ml_client(settings),
        settings=settings,
    )
    app = make_job_app(settings)
    with app.open():
        # Several at once, so a long import does not hold up new uploads.
        app.run_worker(queues=["text", "ml", "backup", "import"], concurrency=3)


def _apply_here(config: SystemConfig) -> None:
    """The worker's own share of the settings (log level, contact email)."""
    if _context is not None:
        apply(config, _context.http)


# First in the queue: a restarted ML service should not wait behind hundreds
# of embedding jobs for its settings.
@tasks.periodic(cron="* * * * *")
@tasks.task(name="configure_ml", queue="ml", queueing_lock="configure-ml", priority=100)
def configure_ml(timestamp: int) -> None:
    """Send the administration's ML settings to the ML services, every
    minute, in case one restarted (it starts from its environment
    variables). Cheap: unchanged settings change nothing there."""
    context = _worker_context()
    with context.sessions() as db:
        send_ml_config(db, context.settings, context.ml)


def send_ml_config(db: Session, settings: Settings, ml: MLClient) -> None:
    """The ML settings of the administration, to every ML service."""
    config = load_config(db, settings)
    _apply_here(config)
    for error in ml.configure(threads=config.ml_threads, keep=[config.embedding_model]):
        log.info("ML service not configured: %s", error)


def queue_ml_configuration(app: App) -> None:
    """Send the ML settings soon (e.g. when the server starts)."""
    task = app.configure_task(
        "paperus:configure_ml", queueing_lock="configure-ml", priority=100
    )
    with contextlib.suppress(AlreadyEnqueued):
        task.defer(timestamp=0)


@tasks.periodic(cron="30 2 * * *")
@tasks.task(name="empty_trash", queue="backup", queueing_lock="empty-trash")
def empty_old_trash(timestamp: int) -> None:
    """Delete for good what has been in the trash longer than the days set
    (Administration → Settings → Trash); nothing if none are set."""
    context = _worker_context()
    with context.sessions() as db:
        days = load_config(db, context.settings).trash_days
        if days is None:
            return
        done = trash.empty(
            db, context.blobs, before=datetime.now(UTC) - timedelta(days=days)
        )
    log.info("emptied the trash: %s", done)


@tasks.task(name="check_integrity", queue="backup", queueing_lock="integrity")
def check_integrity_now(deep: bool = False, remove_unused: bool = False) -> None:
    """Compare the database with the storage (see ``paperus.integrity``)."""
    context = _worker_context()
    with context.sessions() as db:
        report = integrity.check(
            db, context.blobs, deep=deep, remove_unused=remove_unused
        )
    log.info("integrity check: %s", report.model_dump(exclude={"problems"}))


@tasks.periodic(cron="15 4 * * 0")
@tasks.task(name="weekly_integrity", queue="backup", queueing_lock="integrity")
def weekly_integrity(timestamp: int) -> None:
    check_integrity_now()


def queue_integrity_check(
    app: App, *, deep: bool = False, remove_unused: bool = False
) -> None:
    task = app.configure_task("paperus:check_integrity", queueing_lock="integrity")
    with contextlib.suppress(AlreadyEnqueued):
        task.defer(deep=deep, remove_unused=remove_unused)


def queue_empty_trash(app: App) -> None:
    task = app.configure_task("paperus:empty_trash", queueing_lock="empty-trash")
    with contextlib.suppress(AlreadyEnqueued):
        task.defer(timestamp=0)


@tasks.task(name="import_library", queue="import", pass_context=True)
def import_library(job: JobContext, import_id: str) -> None:
    """Run an import someone uploaded (see ``paperus.importing``)."""
    context = _worker_context()
    with context.sessions() as db:
        record = db.get(Import, uuid.UUID(import_id))
        if record is None or record.status != ImportStatus.WAITING:
            return
        if record.blob_sha256 is None:
            return
        with context.blobs.local_file(record.blob_sha256) as path:
            run_import(
                db,
                context.blobs,
                record,
                path=path,
                max_file_bytes=max_upload_bytes(db, context.settings),
                file_added=lambda file_id: queue_text_extraction(job.app, file_id),
            )


def queue_import(app: App, import_id: uuid.UUID, owner: uuid.UUID) -> None:
    """Imports into one owner run one after another (they would find each
    other's new papers and collections only half)."""
    app.configure_task("paperus:import_library", lock=f"import-{owner}").defer(
        import_id=str(import_id)
    )


@tasks.task(name="backup", queue="backup", queueing_lock="backup")
def run_backup(with_files: bool) -> None:
    """Write a backup now, then remove the oldest beyond the number kept."""
    context = _worker_context()
    root = context.settings.backup_path
    create_backup(context.engine, context.blobs, root, with_files=with_files)
    with context.sessions() as db:
        keep = load_backup_config(db).keep
    prune(root, keep)


@tasks.periodic(cron="7 * * * *")
@tasks.task(name="scheduled_backup", queue="backup", pass_context=True)
def scheduled_backup(job: JobContext, timestamp: int) -> None:
    """Every hour: start a backup if the schedule says so."""
    context = _worker_context()
    with context.sessions() as db:
        config = load_backup_config(db)
    last = last_backup_time(context.settings.backup_path)
    if due(last, config.schedule, config.hour, datetime.now(UTC)):
        queue_backup(job.app, with_files=config.with_files)


def queue_backup(app: App, *, with_files: bool) -> bool:
    """Queue a backup; False if one is queued or running already."""
    task = app.configure_task("paperus:backup", queueing_lock="backup")
    try:
        task.defer(with_files=with_files)
    except AlreadyEnqueued:
        return False
    return True
