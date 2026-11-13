"""Lookups waiting in the queue of reading files move to their own queue

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-13 14:00:00.000000

Reference lists, open-access copies, journal versions and authors are
looked up in the queue "lookup" now (``paperus.jobs.LOOKUP``); those
already waiting in "text" go there too, so reading files does not wait
behind them after the update.
"""

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"

TASKS = (
    "fetch_open_access",
    "find_published_versions",
    "find_new_published_versions",
    "link_authors",
    "look_up_authors",
    "find_reference_lists",
    "find_item_references",
    "queue_open_access_sweep",
)


def _move(source: str, target: str) -> None:
    names = ", ".join(f"'paperus:{task}'" for task in TASKS)
    op.execute(
        f"UPDATE procrastinate_jobs SET queue_name = '{target}' "
        f"WHERE status = 'todo' AND queue_name = '{source}' "
        f"AND task_name IN ({names})"
    )


def upgrade() -> None:
    _move("text", "lookup")


def downgrade() -> None:
    _move("lookup", "text")
