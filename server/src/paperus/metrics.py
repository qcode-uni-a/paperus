"""Prometheus metrics, on a port of their own (``PAPERUS_METRICS_PORT``), so
they are not reachable through the public address: requests, searches and
calls to the ML service as they happen, and the library's figures (papers,
storage, background jobs, …) read from the database at each scrape."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from prometheus_client import REGISTRY, Counter, Histogram, start_http_server
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from paperus import usage
from paperus.backup import last_backup_time
from paperus.config import Settings
from paperus.models import (
    Blob,
    Chunk,
    Embedding,
    File,
    FileChunk,
    Group,
    Import,
    ImportStatus,
    Item,
    Note,
    TextStatus,
    User,
)
from paperus.system import load_config

log = logging.getLogger(__name__)

HTTP_REQUESTS = Counter(
    "paperus_http_requests_total",
    "HTTP requests to the server",
    ["method", "route", "status"],
)
HTTP_SECONDS = Histogram(
    "paperus_http_request_duration_seconds",
    "Time to answer an HTTP request",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
SEARCHES = Counter("paperus_searches_total", "Searches, by the mode used", ["mode"])
SEARCH_SECONDS = Histogram(
    "paperus_search_duration_seconds",
    "Time to search (including the query's vector)",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
ML_CALLS = Counter(
    "paperus_ml_calls_total",
    "Calls to the ML service, by outcome",
    ["operation", "outcome"],
)
ML_SECONDS = Histogram(
    "paperus_ml_call_duration_seconds",
    "Time the ML service took to answer",
    ["operation"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
)


@dataclass
class Figures:
    items: int
    items_in_trash: int
    files: int
    files_pending: int
    files_failed: int
    notes: int
    users: int
    groups: int
    storage_bytes: int
    chunks: int
    embedded: int
    embedding_model: str
    imports_running: int
    jobs: dict[str, dict[str, int]]


def library_figures(db: Session, settings: Settings) -> Figures:
    """The library's figures (also for Administration → Server stats)."""
    model = load_config(db, settings).embedding_model
    count = func.count()
    visible_chunks = (
        select(FileChunk.chunk_sha256)
        .join(File, File.id == FileChunk.file_id)
        .where(File.deleted_at.is_(None), FileChunk.in_references.is_(False))
    )
    jobs: dict[str, dict[str, int]] = {}
    for queue, status, number in db.execute(
        text(
            "SELECT queue_name, status::text, count(*) FROM procrastinate_jobs"
            " GROUP BY queue_name, status"
        )
    ):
        jobs.setdefault(queue, {})[status] = number

    def number(query: Any) -> int:  # noqa: ANN401 (any select)
        return int(db.scalar(query) or 0)

    return Figures(
        items=number(select(count).select_from(Item).where(Item.deleted_at.is_(None))),
        items_in_trash=number(
            select(count).select_from(Item).where(Item.deleted_at.is_not(None))
        ),
        files=number(select(count).select_from(File).where(File.deleted_at.is_(None))),
        files_pending=number(
            select(count)
            .select_from(File)
            .where(File.text_status == TextStatus.PENDING, File.deleted_at.is_(None))
        ),
        files_failed=number(
            select(count)
            .select_from(File)
            .where(File.text_status == TextStatus.FAILED, File.deleted_at.is_(None))
        ),
        notes=number(select(count).select_from(Note).where(Note.deleted_at.is_(None))),
        users=number(
            select(count).select_from(User).where(User.deactivated_at.is_(None))
        ),
        groups=number(select(count).select_from(Group)),
        storage_bytes=number(select(func.coalesce(func.sum(Blob.size), 0))),
        chunks=number(
            select(func.count(func.distinct(Chunk.sha256))).where(
                Chunk.sha256.in_(visible_chunks)
            )
        ),
        embedded=number(
            select(count)
            .select_from(Embedding)
            .where(Embedding.model == model, Embedding.chunk_sha256.in_(visible_chunks))
        ),
        embedding_model=model,
        imports_running=number(
            select(count)
            .select_from(Import)
            .where(Import.status.in_([ImportStatus.WAITING, ImportStatus.RUNNING]))
        ),
        jobs=jobs,
    )


class LibraryCollector(Collector):
    """Reads the figures from the database when Prometheus scrapes."""

    def __init__(self, sessions: sessionmaker[Session], settings: Settings) -> None:
        self.sessions = sessions
        self.settings = settings

    def collect(self) -> Iterator[Metric]:
        try:
            with self.sessions() as db:
                figures = library_figures(db, self.settings)
        except Exception:
            log.warning("could not read the library's figures", exc_info=True)
            return
        gauges = {
            "items": "Papers (not in the trash)",
            "items_in_trash": "Papers in the trash",
            "files": "Files (not in the trash)",
            "files_pending": "Files whose text is still being read",
            "files_failed": "Files whose text could not be read",
            "notes": "Notes (not in the trash)",
            "users": "Active people",
            "groups": "Groups",
            "storage_bytes": "Bytes of stored contents",
            "chunks": "Passages to search by meaning",
            "imports_running": "Imports waiting or running",
        }
        for name, description in gauges.items():
            yield GaugeMetricFamily(
                f"paperus_{name}", description, value=float(getattr(figures, name))
            )
        embedded = GaugeMetricFamily(
            "paperus_embedded_chunks",
            "Passages with a vector from the model in use",
            labels=["model"],
        )
        embedded.add_metric([figures.embedding_model], float(figures.embedded))
        yield embedded
        jobs = GaugeMetricFamily(
            "paperus_jobs",
            "Background jobs by queue and status",
            labels=["queue", "status"],
        )
        for queue, statuses in figures.jobs.items():
            for status, number in statuses.items():
                jobs.add_metric([queue, status], float(number))
        yield jobs
        with self.sessions() as db:
            space = usage.usage(db, self.settings)
        if space.disk is not None:
            yield GaugeMetricFamily(
                "paperus_disk_total_bytes",
                "Size of the disk the files are on",
                value=float(space.disk.total),
            )
            yield GaugeMetricFamily(
                "paperus_disk_free_bytes",
                "Free space on the disk the files are on",
                value=float(space.disk.free),
            )
        if space.backups_bytes is not None:
            yield GaugeMetricFamily(
                "paperus_backups_bytes",
                "Space the backups take",
                value=float(space.backups_bytes),
            )
        last = last_backup_time(self.settings.backup_path)
        if last is not None:
            yield GaugeMetricFamily(
                "paperus_last_backup_timestamp_seconds",
                "When the newest backup was written (Unix time)",
                value=last.timestamp(),
            )


_started = False


def serve(port: int, sessions: sessionmaker[Session], settings: Settings) -> None:
    """Start the metrics endpoint (once per process)."""
    global _started
    if _started:
        return
    REGISTRY.register(LibraryCollector(sessions, settings))
    start_http_server(port)
    _started = True
    log.info("Prometheus metrics on port %d", port)
