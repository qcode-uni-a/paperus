"""Lookups waiting in the queue "lookup" move to their service's queue

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-13 17:00:00.000000

The lookups run in a queue per service now (``paperus.jobs``): "arxiv"
(journal versions; reference lists from LaTeX sources), "crossref"
(reference lists, which go on to "arxiv" if they need it) and "openalex"
(authors, open-access copies). Those waiting move there.
"""

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"

QUEUES = {
    "arxiv": ("find_published_versions", "find_new_published_versions"),
    "crossref": ("find_item_references",),
    "openalex": (
        "fetch_open_access",
        "link_authors",
        "look_up_authors",
        "find_reference_lists",
        "queue_open_access_sweep",
    ),
}


def _move(source: str | None, target: str | None) -> None:
    for queue, tasks in QUEUES.items():
        names = ", ".join(f"'paperus:{task}'" for task in tasks)
        op.execute(
            f"UPDATE procrastinate_jobs SET queue_name = '{target or queue}' "
            f"WHERE status = 'todo' AND queue_name = '{source or queue}' "
            f"AND task_name IN ({names})"
        )


def upgrade() -> None:
    _move("lookup", None)


def downgrade() -> None:
    _move(None, "lookup")
