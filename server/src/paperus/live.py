"""Live signals (#46): an open stream for each client that says when the
library changed, so the website and the apps ask ``/api/changes`` at once
rather than within a minute. Only a signal: what changed, and whether the
person may see it, they learn by asking (the change numbers stay the
source of truth, and a client asks anyway after reconnecting).

The transaction that takes a change number notifies Postgres' channel
(``changes._next_change``); Postgres delivers it only when the transaction
commits. Each server process listens on one connection of its own and
wakes its streams.
"""

import asyncio
import contextlib
import logging

import psycopg
from sqlalchemy import Connection, make_url, text

log = logging.getLogger(__name__)

CHANNEL = "paperus_changes"
# Waited before listening again after the connection was lost.
RETRY_SECONDS = 5.0


def notify(connection: Connection) -> None:
    """Signal a change, when ``connection``'s transaction commits."""
    connection.execute(text("SELECT pg_notify(:channel, '')"), {"channel": CHANNEL})


class Signals:
    """The process's listener, and the streams it wakes."""

    def __init__(self, database_url: str) -> None:
        url = make_url(database_url).set(drivername="postgresql")
        self._conninfo = url.render_as_string(hide_password=False)
        self._waiting: set[asyncio.Event] = set()
        self._task: asyncio.Task[None] | None = None
        self.listening = asyncio.Event()
        """Set once the listener listens (for tests)."""

    def subscribe(self) -> asyncio.Event:
        """An event set at each change (until ``unsubscribe``)."""
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._listen())
        event = asyncio.Event()
        self._waiting.add(event)
        return event

    def unsubscribe(self, event: asyncio.Event) -> None:
        self._waiting.discard(event)

    def _wake(self) -> None:
        for event in self._waiting:
            event.set()

    async def _listen(self) -> None:
        while self._waiting:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._conninfo, autocommit=True
                ) as connection:
                    await connection.execute(f"LISTEN {CHANNEL}")
                    self.listening.set()
                    # Something may have changed while not listening.
                    self._wake()
                    async for _ in connection.notifies():
                        self._wake()
                        if not self._waiting:
                            return
            except (psycopg.Error, OSError):
                self.listening.clear()
                log.warning("live signals: listening again", exc_info=True)
                await asyncio.sleep(RETRY_SECONDS)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
