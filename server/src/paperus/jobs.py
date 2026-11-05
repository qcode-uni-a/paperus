"""Background jobs, queued in Postgres with Procrastinate.

The API queues jobs; ``paperus worker`` runs them. A periodic sweep queues
whatever is still pending, so a job that failed to queue is not lost.
"""

import asyncio
import contextlib
import logging
import signal
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx2
from procrastinate import App, Blueprint, JobContext, PsycopgConnector, RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from paperus import auth, integrity, readable, trash
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
        asyncio.run(run_workers(app, _job_limits))


# How often the worker looks whether the number of jobs at once changed.
LIMITS_SECONDS = 30.0


def job_limits(config: SystemConfig) -> dict[str, int]:
    """Jobs at once per queue (Administration → Settings → Job settings);
    one maintenance job (backups, trash, integrity) at a time."""
    return {
        "text": config.jobs_text,
        "ml": config.jobs_ml,
        "import": config.jobs_import,
        "backup": 1,
    }


def _job_limits() -> dict[str, int]:
    context = _worker_context()
    with context.sessions() as db:
        return job_limits(load_config(db, context.settings))


async def run_workers(
    app: App,
    limits: Callable[[], dict[str, int]],
    stop: asyncio.Event | None = None,
) -> None:
    """One worker per queue, so a long import does not hold up new uploads,
    each running as many jobs at once as the settings say. When a number
    changes, that queue's worker is replaced: the old one finishes its
    running jobs and takes no new ones."""
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(signum, stop.set)
    running: dict[str, tuple[int, asyncio.Task[None]]] = {}
    stopping: list[asyncio.Task[None]] = []
    async with app.open_async():
        while not stop.is_set():
            try:
                wanted = await asyncio.to_thread(limits)
            except Exception:
                log.warning("could not read the job settings", exc_info=True)
                wanted = {queue: number for queue, (number, _) in running.items()}
                wanted = wanted or job_limits(SystemConfig(embedding_model=""))
            for queue, number in wanted.items():
                current = running.get(queue)
                if current is not None and not current[1].done():
                    if current[0] == number:
                        continue
                    log.info("%s: %d jobs at once (was %d)", queue, number, current[0])
                    current[1].cancel()
                    stopping.append(current[1])
                elif current is not None and not current[1].cancelled():
                    if error := current[1].exception():
                        log.error("the %s worker stopped: %r", queue, error)
                running[queue] = (
                    number,
                    asyncio.create_task(
                        app.run_worker_async(
                            queues=[queue],
                            concurrency=number,
                            name=queue,
                            install_signal_handlers=False,
                        )
                    ),
                )
            stopping = [task for task in stopping if not task.done()]
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), LIMITS_SECONDS)
        workers = [task for _, task in running.values()] + stopping
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


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


@tasks.periodic(cron="30 * * * *")
@tasks.task(name="empty_trash", queue="backup", queueing_lock="empty-trash")
def empty_old_trash(timestamp: int) -> None:
    """At half past the night hour (Administration → Settings → Job
    settings), or when asked (``timestamp`` 0): delete for good what has been
    in the trash longer than the days set; nothing if none are set."""
    context = _worker_context()
    with context.sessions() as db:
        config = load_config(db, context.settings)
        if config.trash_days is None:
            return
        if (
            timestamp
            and datetime.fromtimestamp(timestamp, UTC).hour != config.night_hour
        ):
            return
        done = trash.empty(
            db,
            context.blobs,
            before=datetime.now(UTC) - timedelta(days=config.trash_days),
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


# Finished jobs are kept this long (failed ones longer, to look into them).
KEEP_JOBS = timedelta(days=7)
KEEP_FAILED_JOBS = timedelta(days=30)


@tasks.periodic(cron="20 * * * *")
@tasks.task(name="tidy", queue="backup", queueing_lock="tidy", pass_context=True)
async def tidy(job: JobContext, timestamp: int) -> None:
    """Every hour: retry jobs whose worker stopped (killed mid-job). At
    twenty past the night hour also: delete finished jobs and expired login
    sessions, which nothing else removes."""
    manager = job.app.job_manager
    for stalled in await manager.get_stalled_jobs():
        log.info(
            "retrying job %s (%s): its worker stopped", stalled.id, stalled.task_name
        )
        await manager.retry_job(stalled)
    context = _worker_context()

    def night_hour() -> int:
        with context.sessions() as db:
            return load_config(db, context.settings).night_hour

    hour = datetime.fromtimestamp(timestamp, UTC).hour
    if timestamp and hour != await asyncio.to_thread(night_hour):
        return
    await manager.delete_old_jobs(nb_hours=int(KEEP_JOBS.total_seconds() // 3600))
    await manager.delete_old_jobs(
        nb_hours=int(KEEP_FAILED_JOBS.total_seconds() // 3600),
        include_failed=True,
        include_cancelled=True,
        include_aborted=True,
    )

    def remove_sessions() -> int:
        with context.sessions() as db:
            removed = auth.remove_expired_sessions(db)
            db.commit()
            return removed

    sessions = await asyncio.to_thread(remove_sessions)
    log.info("tidied up: old jobs deleted, %d expired login sessions", sessions)


def queue_tidy(app: App) -> None:
    task = app.configure_task("paperus:tidy", queueing_lock="tidy")
    with contextlib.suppress(AlreadyEnqueued):
        task.defer(timestamp=0)


@tasks.periodic(cron="45 * * * *")
@tasks.task(name="scheduled_integrity", queue="backup")
def scheduled_integrity(timestamp: int) -> None:
    """Every hour: start an integrity check if its schedule says so (at the
    night hour, every night or on Sundays)."""
    context = _worker_context()
    with context.sessions() as db:
        config = load_config(db, context.settings)
        report = integrity.last_report(db)
    now = datetime.fromtimestamp(timestamp, UTC)
    last = report.checked_at if report else None
    if due(last, config.integrity_schedule, config.night_hour, now, weekday=6):
        check_integrity_now()


@tasks.task(name="readable_copy", queue="backup", queueing_lock="readable-copy")
def update_readable_copy(remove: bool = False) -> None:
    """Bring the readable copy in line with the library (or remove it)."""
    context = _worker_context()
    root = context.settings.copy_path
    with context.sessions() as db:
        config = load_config(db, context.settings)
        if remove:
            report = readable.remove_copy(db, root)
        elif config.copy_enabled:
            report = readable.sync(
                db, context.blobs, root, config.copy_template, links=config.copy_links
            )
        else:
            return
    log.info("readable copy: %s", report.model_dump())


@tasks.periodic(cron="50 * * * *")
@tasks.task(name="nightly_readable_copy", queue="backup")
def nightly_readable_copy(timestamp: int) -> None:
    """At ten to the end of the night hour (after the trash and the integrity
    check): the readable copy, if switched on."""
    context = _worker_context()
    with context.sessions() as db:
        config = load_config(db, context.settings)
    hour = datetime.fromtimestamp(timestamp, UTC).hour
    if config.copy_enabled and hour == config.night_hour:
        update_readable_copy()


def queue_readable_copy(app: App, *, remove: bool = False) -> None:
    task = app.configure_task("paperus:readable_copy", queueing_lock="readable-copy")
    with contextlib.suppress(AlreadyEnqueued):
        task.defer(remove=remove)


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
        # Running: the job is being retried after its worker stopped in the
        # middle; importing again is safe (what is there is recognised).
        if record is None or record.status not in (
            ImportStatus.WAITING,
            ImportStatus.RUNNING,
        ):
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
