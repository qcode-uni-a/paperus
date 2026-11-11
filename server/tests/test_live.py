"""The listener behind live signals (``paperus.live``); the stream itself
is tested in test_sync.py."""

import asyncio

import pytest
from sqlalchemy import Engine

from paperus import live


def test_listens_again_and_stops_when_nobody_waits(
    engine: Engine, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "RETRY_SECONDS", 0.01)

    async def unreachable() -> None:
        signals = live.Signals("postgresql+psycopg://nobody:x@127.0.0.1:1/none")
        woken = signals.subscribe()
        await asyncio.sleep(0.2)
        assert not signals.listening.is_set() and not woken.is_set()
        # Nobody waiting: it gives up trying.
        signals.unsubscribe(woken)
        assert signals._task is not None
        await asyncio.wait_for(signals._task, 2)

    async def nobody_left() -> None:
        signals = live.Signals(database_url)
        woken = signals.subscribe()
        await asyncio.wait_for(signals.listening.wait(), 10)
        signals.unsubscribe(woken)
        # The next signal finds nobody: the listener ends.
        with engine.begin() as connection:
            live.notify(connection)
        assert signals._task is not None
        await asyncio.wait_for(signals._task, 10)
        await signals.close()

    asyncio.run(unreachable())
    asyncio.run(nobody_left())
