"""Cover pages of files: noted, and left out of their text

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-13 19:00:00.000000

``files.cover_pages``: the pages (from 1) a site put in front of or behind
the paper (``paperus.covers``). Files read before are looked at here, by
the same rule on their stored text: the first page (of a file of two or
more) or the last (of three or more) when it is short and says what
covers say; those pages' passages are taken out of the file's text. The
phrases are copied here, as the rule in the code may change later.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0018"
down_revision: str | None = "0017"

MOST_WORDS = 300
OWN = (
    "to cite this article",
    "view the article online for updates and enhancements",
    "this content downloaded from",
    "your use of the jstor archive",
    "jstor is a not-for-profit service",
    "see discussions, stats, and author profiles for this publication",
    "full terms & conditions of access and use",
    "cambridge core terms of use",
    "link to license to see what you are allowed to do",
    "this document is downloaded from",
)
SHARED = (
    "downloaded from",
    "terms of use",
    "terms and conditions",
    "permanent link",
    "persistent link",
    "rights / license",
    "this version is available at",
    "citation for published version",
    "general rights",
    "take down policy",
    "copyright and moral rights",
)


def _quoted(phrase: str) -> str:
    return "'" + phrase.replace("'", "''") + "'"


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column(
            "cover_pages",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    own = " OR ".join(f"position({_quoted(p)} in t) > 0" for p in OWN)
    shared = " + ".join(f"(position({_quoted(p)} in t) > 0)::int" for p in SHARED)
    op.execute(
        f"""
        CREATE TEMPORARY TABLE found_covers ON COMMIT DROP AS
        WITH pages AS (
            SELECT fc.file_id, fc.page,
                   lower(regexp_replace(string_agg(c.text, ' ' ORDER BY fc.position),
                                        '\\s+', ' ', 'g')) AS t
            FROM file_chunks fc JOIN chunks c ON c.sha256 = fc.chunk_sha256
            WHERE fc.page IS NOT NULL
            GROUP BY fc.file_id, fc.page
        ), last AS (
            SELECT file_id, max(page) AS n FROM pages GROUP BY file_id
        )
        SELECT p.file_id, p.page
        FROM pages p JOIN last l USING (file_id)
        WHERE ((p.page = 1 AND l.n > 1) OR (p.page = l.n AND l.n > 2))
          AND array_length(regexp_split_to_array(btrim(p.t), ' '), 1) <= {MOST_WORDS}
          AND (({own}) OR ({shared}) >= 2)
        """
    )
    op.execute(
        """
        UPDATE files SET cover_pages = covers.pages
        FROM (SELECT file_id, jsonb_agg(page ORDER BY page) AS pages
              FROM found_covers GROUP BY file_id) covers
        WHERE files.id = covers.file_id
        """
    )
    op.execute(
        """
        DELETE FROM file_chunks fc USING found_covers f
        WHERE fc.file_id = f.file_id AND fc.page = f.page
        """
    )


def downgrade() -> None:
    # The covers' passages are not brought back: "Read all files again"
    # (Administration → Jobs) reads them anew.
    op.drop_column("files", "cover_pages")
