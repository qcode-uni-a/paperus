"""The log, kept in the database as well (Administration → Logs): what the
server, the worker and people's browser extensions report, readable where
``docker compose logs`` is out of reach. paperus's own messages at the level
set in the administration, other libraries' from warnings up; entries older
than ``KEEP`` (or beyond ``MOST``) go in the nightly tidy-up."""

import logging
import queue
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, delete, insert, select
from sqlalchemy.orm import Session

from paperus.models import LogEntry

KEEP = timedelta(days=14)
MOST = 100_000
MAX_MESSAGE = 8000
_BATCH = 200

_installed: "DatabaseHandler | None" = None


class DatabaseHandler(logging.Handler):
    """Writes entries from a thread of its own with its own connections, so
    logging never waits for the database; when that is away, the entries
    are in the container's log only. What the thread itself logs (the
    database driver's warnings) stays out, or it would never end."""

    def __init__(self, engine: Engine, source: str) -> None:
        super().__init__()
        self.setFormatter(logging.Formatter("%(message)s"))
        self.addFilter(_ours_or_warnings)
        self.engine = engine
        self.source = source
        self.entries: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        self.thread = threading.Thread(
            target=self._write, name="paperus-logbook", daemon=True
        )
        self.thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        if threading.current_thread() is self.thread:
            return
        try:
            message = self.format(record)
        except Exception:  # as logging.Handler does
            self.handleError(record)
            return
        self.entries.put(
            {
                "at": datetime.fromtimestamp(record.created, UTC),
                "level": record.levelname.lower()[:10],
                "source": self.source,
                "logger": record.name[:100],
                "message": message[:MAX_MESSAGE],
            }
        )

    def _write(self) -> None:
        while True:
            batch = [self.entries.get()]
            while len(batch) < _BATCH:
                try:
                    batch.append(self.entries.get_nowait())
                except queue.Empty:
                    break
            try:
                with self.engine.begin() as connection:
                    connection.execute(insert(LogEntry), batch)
            except Exception:  # the database is away
                pass


def _ours_or_warnings(record: logging.LogRecord) -> bool:
    """paperus's messages at its level (the "paperus" logger's, set in the
    administration); other libraries' only from warnings up."""
    return record.name.startswith("paperus") or record.levelno >= logging.WARNING


def install(engine: Engine, source: str) -> None:
    """Keep this process's log in the database too ("server" or "worker");
    once per process."""
    global _installed
    if _installed is not None:
        return
    _installed = DatabaseHandler(engine, source)
    logging.getLogger().addHandler(_installed)


def prune(db: Session, now: datetime | None = None) -> int:
    """Delete entries older than ``KEEP`` and beyond the newest ``MOST``;
    how many went."""
    now = now or datetime.now(UTC)
    result = db.execute(delete(LogEntry).where(LogEntry.at < now - KEEP))
    removed = int(getattr(result, "rowcount", 0) or 0)
    oldest_kept = db.scalar(
        select(LogEntry.id).order_by(LogEntry.id.desc()).offset(MOST).limit(1)
    )
    if oldest_kept is not None:
        result = db.execute(delete(LogEntry).where(LogEntry.id <= oldest_kept))
        removed += int(getattr(result, "rowcount", 0) or 0)
    return removed
