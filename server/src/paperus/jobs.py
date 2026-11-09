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
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx2
from procrastinate import App, Blueprint, JobContext, PsycopgConnector, RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued
from procrastinate.types import JSONValue
from sqlalchemy import Engine, exists, func, make_url, or_, select
from sqlalchemy.orm import Session, sessionmaker

from paperus import (
    auth,
    authors,
    integrity,
    item_references,
    missing,
    ocr,
    published,
    readable,
    system,
    trash,
)
from paperus import export as exports
from paperus.access import Access
from paperus.backup import create_backup, due, last_backup_time, prune
from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker
from paperus.embedding import (
    details_missing_embeddings,
    embed_details,
    embed_file,
    embed_note,
    files_missing_embeddings,
    notes_missing_embeddings,
)
from paperus.importing import Export
from paperus.importing.apply import Files as FileSource
from paperus.importing.references import complete
from paperus.importing.run import run_export, run_import
from paperus.metadata import make_http_client
from paperus.ml import MLClient, MLRejected, MLUnavailable, make_ml_client
from paperus.models import File, FileChunk, Import, ImportStatus, Item, User, Version
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


def _queue(
    app: App,
    task: str,
    lock: str,
    priority: int | None = None,
    **arguments: JSONValue,
) -> bool:
    """Queue a job, unless one with the same lock is queued already; whether
    it was queued.

    By task name through ``app``: the blueprint's task objects are shared
    between apps (e.g. in tests).
    """
    deferrer = app.configure_task(
        f"paperus:{task}", queueing_lock=lock, priority=priority
    )
    try:
        deferrer.defer(**arguments)
    except AlreadyEnqueued:
        return False
    return True


@tasks.task(name="extract_text", queue="text", retry=2, pass_context=True)
def extract_text(job: JobContext, file_id: str) -> None:
    context = _worker_context()
    with context.sessions() as db:
        config = load_config(db, context.settings)
        scans = process_file(
            db, context.blobs, uuid.UUID(file_id), context.http, ocr=config.ocr
        )
        # A paper without reference list: never looked at, or its file has one.
        item_id = db.scalar(
            select(Version.item_id)
            .join(File)
            .join(Item, Item.id == Version.item_id)
            .where(
                File.id == uuid.UUID(file_id),
                Item.references_source.is_(None),
                or_(
                    Item.references_checked_at.is_(None),
                    exists().where(
                        FileChunk.file_id == File.id, FileChunk.in_references
                    ),
                ),
            )
        )
    queue_embedding(job.app, uuid.UUID(file_id))
    if scans:
        queue_ocr(job.app, uuid.UUID(file_id))
    if item_id is not None and config.find_references:
        # Its PDF may have the reference list the paper has none of yet.
        queue_references(job.app, item_id)


# Scanned pages, one file at a time (a few seconds per page on a CPU), in a
# queue of their own so they do not hold up embedding. Retried like
# embedding while the ML service is down; the sweep catches the rest.
@tasks.task(
    name="ocr_file",
    queue="ocr",
    retry=RetryStrategy(
        max_attempts=10, exponential_wait=2, retry_exceptions={MLUnavailable}
    ),
    pass_context=True,
)
def ocr_file(job: JobContext, file_id: str) -> None:
    context = _worker_context()
    with context.sessions() as db:
        config = load_config(db, context.settings)
        if not config.ocr:
            return
        again = ocr.read_scans(
            db, context.blobs, context.ml, config.ocr_model, uuid.UUID(file_id)
        )
    for other in again:
        queue_text_extraction(job.app, other)


@tasks.periodic(cron="*/10 * * * *")
@tasks.task(
    name="queue_pending_ocr", queue="ocr", queueing_lock="ocr-sweep", pass_context=True
)
def queue_pending_ocr(job: JobContext, timestamp: int) -> None:
    context = _worker_context()
    with context.sessions() as db:
        if not load_config(db, context.settings).ocr:
            return
        for file_id in ocr.waiting(db):
            queue_ocr(job.app, file_id)


def queue_ocr(app: App, file_id: uuid.UUID) -> None:
    _queue(app, "ocr_file", f"ocr-{file_id}", file_id=str(file_id))


def queue_ocr_sweep(app: App) -> None:
    """Look for scans waiting for OCR now (e.g. after switching it on)."""
    _queue(app, "queue_pending_ocr", "ocr-sweep", timestamp=0)


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


@tasks.task(
    name="embed_details",
    queue="ml",
    retry=RetryStrategy(
        max_attempts=10, exponential_wait=2, retry_exceptions={MLUnavailable}
    ),
)
def embed_papers_details() -> None:
    """Papers' titles and abstracts (``paperus.details``), all at once: each
    is one short passage."""
    context = _worker_context()
    with context.sessions() as db:
        model = load_config(db, context.settings).embedding_model
        count = embed_details(db, context.ml, model)
    log.info("embedded %d papers' details", count)


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
        # What the ML service's vectors are stored as: a switch to another
        # model file (CPU to GPU) re-embeds like a change of model.
        try:
            vectors = context.ml.vectors_name(model)
        except (MLUnavailable, MLRejected) as error:
            log.info("not looking for missing embeddings: %s", error)
            return
        if vectors != system.vectors_in_use(db, model):
            system.save_vectors_in_use(db, model, vectors)
            db.commit()
        for file_id in files_missing_embeddings(db, vectors):
            queue_embedding(job.app, file_id)
        for note_id in notes_missing_embeddings(db, vectors):
            queue_note_embedding(job.app, note_id)
        if details_missing_embeddings(db, vectors, limit=1):
            _queue(job.app, "embed_details", "embed-details")


def queue_embedding_sweep(app: App) -> None:
    """Look for missing embeddings now (e.g. after the model changed)."""
    _queue(app, "queue_missing_embeddings", "embedding-sweep", timestamp=0)


def queue_text_sweep(app: App) -> None:
    """Look for files whose text is still pending now."""
    _queue(app, "queue_pending_files", "sweep", timestamp=0)


def queue_note_embedding(app: App, note_id: uuid.UUID) -> None:
    _queue(app, "embed_note", f"embed-note-{note_id}", note_id=str(note_id))


def queue_embedding(app: App, file_id: uuid.UUID) -> None:
    _queue(app, "embed_file", f"embed-{file_id}", file_id=str(file_id))


@tasks.periodic(cron="*/5 * * * *")
@tasks.task(
    name="queue_pending_files", queue="text", queueing_lock="sweep", pass_context=True
)
def queue_pending_files(job: JobContext, timestamp: int) -> None:
    context = _worker_context()
    with context.sessions() as db:
        for file_id in pending_files(db):
            queue_text_extraction(job.app, file_id)


# Papers without a file (Manage → Missing → Try all): one download each.
@tasks.task(name="fetch_open_access", queue="text", pass_context=True)
def fetch_open_access(
    job: JobContext, item_id: str, user_id: str | None, section: str = "file"
) -> None:
    context = _worker_context()
    which: missing.Section = "journal" if section == "journal" else "file"
    add = missing.add_journal_copy if which == "journal" else missing.add_open_access
    with context.sessions() as db:
        item = db.get(Item, uuid.UUID(item_id))
        if item is None or not db.scalar(
            select(func.count())
            .select_from(Item)
            .where(Item.id == item.id, *missing.conditions(which))
        ):
            return  # gone, or it has the file by now
        file = add(
            db,
            context.http,
            context.blobs,
            item,
            contact_email=load_config(db, context.settings).contact_email,
            max_bytes=max_upload_bytes(db, context.settings),
            user_id=uuid.UUID(user_id) if user_id else None,
        )
        file_id = file.id if file is not None else None
    if file_id is not None:
        queue_text_extraction(job.app, file_id)


def queue_open_access(
    app: App, item_id: uuid.UUID, user_id: uuid.UUID | None, section: str = "file"
) -> None:
    _queue(
        app,
        "fetch_open_access",
        f"open-access-{item_id}",
        item_id=str(item_id),
        user_id=str(user_id) if user_id else None,
        section=section,
    )


# Preprints' published versions (Administration → Settings → Server).
PUBLISHED_PER_HOUR = 40


@tasks.periodic(cron="20 * * * *")
@tasks.task(
    name="find_published_versions",
    queue="text",
    queueing_lock="find-published",
    pass_context=True,
)
def find_published_versions(job: JobContext, timestamp: int) -> None:
    """A few dozen preprints an hour, each at most once a month: arXiv and
    OpenAlex are asked for their journal versions. Found ones are added;
    with open-access copies on, the journal's PDF is tried too."""
    context = _worker_context()
    with context.sessions() as db:
        config = load_config(db, context.settings)
        if not config.find_published:
            return
        items = published.waiting(db, PUBLISHED_PER_HOUR)
        upgraded = published.check(
            db, context.http, items, contact_email=config.contact_email
        )
        found = [(item.id, item.added_by) for item in upgraded]
    log.info("published versions: %d of %d preprints", len(found), len(items))
    if config.open_access_auto:
        for item_id, added_by in found:
            queue_open_access(job.app, item_id, added_by, "journal")


def queue_published_check(app: App) -> None:
    _queue(app, "find_published_versions", "find-published", timestamp=0)


@tasks.periodic(cron="*/5 * * * *")
@tasks.task(
    name="link_authors",
    queue="text",
    lock="link-authors",
    queueing_lock="link-authors",
    pass_context=True,
)
def link_authors(job: JobContext, timestamp: int) -> None:
    """The authors of papers added or changed since, linked to people
    (``paperus.authors``); at first, every paper's."""
    context = _worker_context()
    with context.sessions() as db:
        done = authors.link_waiting(db)
    if done:
        log.info("authors: linked those of %d papers", done)


@tasks.periodic(cron="50 * * * *")
@tasks.task(
    name="look_up_authors",
    queue="text",
    lock="link-authors",
    queueing_lock="look-up-authors",
    pass_context=True,
)
def look_up_authors(job: JobContext, timestamp: int) -> None:
    """Papers' authors at OpenAlex (ids, ORCID iDs, affiliations), for
    papers never looked up; a thousand an hour (``paperus.authors``)."""
    context = _worker_context()
    with context.sessions() as db:
        config = load_config(db, context.settings)
        if not config.find_authors:
            return
        known = authors.check_waiting(
            db, context.http, contact_email=config.contact_email
        )
        authors.link_waiting(db)
    log.info("authors: %d papers known to OpenAlex", known)


def queue_author_linking(app: App) -> None:
    """Link authors now, and look them up at OpenAlex (if that is on)."""
    _queue(app, "link_authors", "link-authors", timestamp=0)
    _queue(app, "look_up_authors", "look-up-authors", timestamp=0)


# Papers' reference lists (Administration → Settings → Server). One job at a
# time (the lock), so the pauses between requests to arXiv hold.
REFERENCES_LOCK = "find-references"


@tasks.periodic(cron="40 * * * *")
@tasks.task(
    name="find_reference_lists",
    queue="text",
    lock=REFERENCES_LOCK,
    queueing_lock="find-reference-lists",
    pass_context=True,
)
def find_reference_lists(job: JobContext, timestamp: int) -> None:
    """A few dozen papers an hour, never looked at first: their reference
    lists from arXiv, Crossref or their PDFs (``paperus.item_references``)."""
    context = _worker_context()
    with context.sessions() as db:
        config = load_config(db, context.settings)
        if not config.find_references:
            return
        looked, found = item_references.check_waiting(
            db, context.http, contact_email=config.contact_email
        )
    log.info("reference lists: %d found for %d papers", found, looked)


@tasks.task(
    name="find_item_references",
    queue="text",
    lock=REFERENCES_LOCK,
    pass_context=True,
)
def find_item_references(job: JobContext, item_id: str, again: bool = False) -> None:
    """One paper's reference list: after its file was read (if it has none
    yet, and the setting is on), or ``again`` when someone asks."""
    context = _worker_context()
    with context.sessions() as db:
        config = load_config(db, context.settings)
        item = db.get(Item, uuid.UUID(item_id))
        if item is None or not (
            again or (config.find_references and item.references_source is None)
        ):
            return
        item_references.check(
            db, context.http, item, contact_email=config.contact_email
        )


def queue_reference_lists(app: App) -> None:
    _queue(app, "find_reference_lists", "find-reference-lists", timestamp=0)


def queue_references(app: App, item_id: uuid.UUID, *, again: bool = False) -> None:
    _queue(
        app,
        "find_item_references",
        f"references-{item_id}",
        item_id=str(item_id),
        again=again,
    )


# Administration → Settings → Server: open-access copies by themselves.
OPEN_ACCESS_WAIT = timedelta(minutes=2)
OPEN_ACCESS_PER_SWEEP = 200


@tasks.periodic(cron="*/10 * * * *")
@tasks.task(
    name="queue_open_access_sweep",
    queue="text",
    queueing_lock="open-access-sweep",
    pass_context=True,
)
def queue_open_access_sweep(job: JobContext, timestamp: int) -> None:
    """Papers added without a file (by hand, the extension, AI assistants,
    imports) get an open-access copy tried, if the setting is on; a few
    hundred per sweep, so a large import is worked through politely."""
    context = _worker_context()
    with context.sessions() as db:
        if not load_config(db, context.settings).open_access_auto:
            return
        waiting = missing.never_tried(
            db,
            added_before=datetime.now(UTC) - OPEN_ACCESS_WAIT,
            limit=OPEN_ACCESS_PER_SWEEP,
        )
    for item_id, added_by in waiting:
        queue_open_access(job.app, item_id, added_by)


def queue_text_extraction(app: App, file_id: uuid.UUID) -> None:
    """Queue extraction for a file, unless it is queued already."""
    _queue(app, "extract_text", str(file_id), file_id=str(file_id))


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
        "ocr": 1,
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
    keep = [config.embedding_model]
    # The reranker too while search uses it ("auto": with a GPU).
    if config.rerank == "on":
        keep.append(config.rerank_model)
    elif config.rerank == "auto":
        try:
            if ml.device() == "cuda":
                keep.append(config.rerank_model)
        except (MLUnavailable, MLRejected):
            pass
    for error in ml.configure(threads=config.ml_threads, keep=keep):
        log.info("ML service not configured: %s", error)


def queue_ml_configuration(app: App) -> None:
    """Send the ML settings soon (e.g. when the server starts)."""
    _queue(app, "configure_ml", "configure-ml", priority=100, timestamp=0)


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
    _queue(app, "tidy", "tidy", timestamp=0)


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
    _queue(app, "readable_copy", "readable-copy", remove=remove)


def queue_integrity_check(
    app: App, *, deep: bool = False, remove_unused: bool = False
) -> None:
    _queue(app, "check_integrity", "integrity", deep=deep, remove_unused=remove_unused)


def queue_empty_trash(app: App) -> None:
    _queue(app, "empty_trash", "empty-trash", timestamp=0)


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
        with contextlib.ExitStack() as stack:
            path = stack.enter_context(context.blobs.local_file(record.blob_sha256))
            parts = [
                (
                    stack.enter_context(context.blobs.local_file(part.blob_sha256)),
                    part.filename,
                )
                for part in record.parts
                if part.blob_sha256 is not None
            ]
            run_import(
                db,
                context.blobs,
                record,
                path=path,
                parts=parts,
                max_file_bytes=max_upload_bytes(db, context.settings),
                file_added=lambda file_id: queue_text_extraction(job.app, file_id),
                http=context.http,
            )


@tasks.task(name="import_references", queue="import", pass_context=True)
def import_references(job: JobContext, import_id: str, item_id: str) -> None:
    """Add a paper's references that have a DOI or arXiv ID (``Import all``
    on its page), as an import into a collection named after it."""
    context = _worker_context()
    with context.sessions() as db:
        record = db.get(Import, uuid.UUID(import_id))
        if record is None or record.status not in (
            ImportStatus.WAITING,
            ImportStatus.RUNNING,
        ):
            return

        def read() -> AbstractContextManager[tuple[Export, FileSource]]:
            # run_export has checked that the person is there and may log in.
            return item_references.reading_for_import(
                db,
                Access.of(db, db.get_one(User, record.user_id)),
                uuid.UUID(item_id),
                lambda export: complete(export, context.http),
            )

        run_export(
            db,
            context.blobs,
            record,
            read,
            max_file_bytes=max_upload_bytes(db, context.settings),
        )


def queue_reference_import(
    app: App, import_id: uuid.UUID, owner: uuid.UUID, item_id: uuid.UUID
) -> None:
    """Like other imports, one after another per owner."""
    app.configure_task("paperus:import_references", lock=f"import-{owner}").defer(
        import_id=str(import_id), item_id=str(item_id)
    )


def queue_import(app: App, import_id: uuid.UUID, owner: uuid.UUID) -> None:
    """Imports into one owner run one after another (they would find each
    other's new papers and collections only half)."""
    app.configure_task("paperus:import_library", lock=f"import-{owner}").defer(
        import_id=str(import_id)
    )


@tasks.task(name="export_library", queue="import")
def export_library(export_id: str) -> None:
    """Write an export someone asked for (see ``paperus.export``)."""
    context = _worker_context()
    exports.run(context.sessions, context.blobs, context.settings, uuid.UUID(export_id))


def queue_export(app: App, export_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """A person's exports are written one after another."""
    app.configure_task("paperus:export_library", lock=f"export-{user_id}").defer(
        export_id=str(export_id)
    )


@tasks.periodic(cron="15 * * * *")
@tasks.task(
    name="remove_expired_exports", queue="backup", queueing_lock="expired-exports"
)
def remove_expired_exports(timestamp: int) -> None:
    """Every hour: delete exports older than a day."""
    context = _worker_context()
    with context.sessions() as db:
        removed = exports.remove_expired(db, context.settings)
    if removed:
        log.info("removed %d expired exports", removed)


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
    return _queue(app, "backup", "backup", with_files=with_files)
