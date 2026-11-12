"""Likely duplicates across the library, with a recommendation which paper
to keep (Manage → Duplicates). Merging itself is ``paperus.merge``."""

import re
import unicodedata
import uuid
from dataclasses import dataclass, field

from sqlalchemy import (
    ColumnElement,
    Text,
    cast,
    func,
    literal,
    literal_column,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from paperus import library
from paperus.access import Access
from paperus.models import (
    FileRole,
    Item,
    MetadataSource,
    NotDuplicate,
    Note,
    NoteItem,
    VersionKind,
)

Reason = str  # "identifier", "file", "title"

# Pairs of papers the person can see that share an identifier or a file, or
# whose titles are the same apart from case, spaces and punctuation.
_PAIRS = text(
    """
    WITH visible AS (
        SELECT id, title FROM items
        WHERE deleted_at IS NULL AND library_id = ANY(CAST(:libraries AS uuid[]))
    ),
    ids AS (
        SELECT DISTINCT v.item_id, i.scheme, i.value
        FROM identifiers i JOIN versions v ON v.id = i.version_id
             JOIN visible ON visible.id = v.item_id
        WHERE i.scheme <> 'url'
    ),
    blobs AS (
        SELECT DISTINCT v.item_id, f.blob_sha256
        FROM files f JOIN versions v ON v.id = f.version_id
             JOIN visible ON visible.id = v.item_id
        WHERE f.deleted_at IS NULL
    ),
    titles AS (
        SELECT id, regexp_replace(lower(title), '[^[:alnum:]]+', '', 'g') AS t
        FROM visible
    ),
    found AS (
        SELECT a.item_id AS a, b.item_id AS b, 'identifier' AS reason
        FROM ids a JOIN ids b
          ON a.scheme = b.scheme AND a.value = b.value AND a.item_id < b.item_id
        UNION ALL
        SELECT a.item_id, b.item_id, 'file'
        FROM blobs a JOIN blobs b
          ON a.blob_sha256 = b.blob_sha256 AND a.item_id < b.item_id
        UNION ALL
        SELECT a.id, b.id, 'title'
        FROM titles a JOIN titles b ON a.t = b.t AND a.id < b.id
        WHERE length(a.t) >= 12
    )
    SELECT a, b, array_agg(DISTINCT reason ORDER BY reason) AS reasons
    FROM found
    WHERE NOT EXISTS (
        SELECT 1 FROM not_duplicates nd
        WHERE nd.item_a = found.a AND nd.item_b = found.b
    )
    GROUP BY a, b
    ORDER BY min(CASE reason WHEN 'identifier' THEN 0 WHEN 'file' THEN 1 ELSE 2 END),
             a, b
    LIMIT :limit
    """
)


@dataclass
class Pair:
    keep: Item
    merge: Item
    """The one to merge into ``keep`` (it goes to the trash)."""
    reasons: list[Reason]
    why: list[str] = field(default_factory=list)
    """Why ``keep`` is recommended."""
    can_merge: bool = True


def find(db: Session, access: Access, limit: int = 200) -> list[Pair]:
    rows = db.execute(_PAIRS, {"libraries": access.readable, "limit": limit}).all()
    ids = {row.a for row in rows} | {row.b for row in rows}
    items = {item.id: item for item in db.scalars(select(Item).where(Item.id.in_(ids)))}
    notes = dict(
        db.execute(
            select(NoteItem.item_id, func.count())
            .join(Note, Note.id == NoteItem.note_id)
            .where(
                NoteItem.item_id.in_(ids),
                Note.deleted_at.is_(None),
                Note.library_id.in_(access.readable),
            )
            .group_by(NoteItem.item_id)
        ).all()
    )
    return [
        _recommend(access, items[row.a], items[row.b], list(row.reasons), notes)
        for row in rows
        # The same title alone: two works can share one ("Introduction to
        # Quantum Optics" by different authors); only with the same first
        # author, or where one names none.
        if list(row.reasons) != ["title"]
        or _same_first_author(items[row.a], items[row.b])
    ]


def _first_author(item: Item) -> str | None:
    names = library.author_names(library.citation_csl(item))
    if not names:
        return None
    family = names[0].split(",")[0]
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKD", family).lower()) or None


def _same_first_author(a: Item, b: Item) -> bool:
    first, second = _first_author(a), _first_author(b)
    return first is None or second is None or first == second


def _merits(
    access: Access, item: Item, notes: dict[uuid.UUID, int]
) -> list[tuple[int, str]]:
    """What speaks for keeping the paper: (weight, reason); only what the
    person can see counts (others' private tags and collections do not)."""
    found: list[tuple[int, str]] = []
    versions = item.versions
    if any(v.kind == VersionKind.PUBLISHED and v.identifiers for v in versions):
        found.append((8, "has the published version"))
    elif any(v.identifiers for v in versions):
        found.append((4, "has an identifier (DOI or arXiv)"))
    if all(v.metadata_source == MetadataSource.FILE for v in versions):
        found.append((-6, ""))  # details only guessed from the file
    if any(
        f.role == FileRole.MAIN and f.deleted_at is None
        for v in versions
        for f in v.files
    ):
        found.append((3, "has the PDF"))
    tags = [t for t in item.tag_links if access.can_read(t.tag.library_id)]
    if tags:
        found.append((min(len(tags), 3), "has more tags"))
    held = [
        c for c in item.collection_links if access.can_read(c.collection.library_id)
    ]
    if held:
        found.append((min(len(held), 3), "is in more collections"))
    if notes.get(item.id):
        found.append((2, "has notes"))
    return found


def _recommend(
    access: Access,
    a: Item,
    b: Item,
    reasons: list[Reason],
    notes: dict[uuid.UUID, int],
) -> Pair:
    merits_a, merits_b = _merits(access, a, notes), _merits(access, b, notes)
    score_a, score_b = sum(w for w, _ in merits_a), sum(w for w, _ in merits_b)
    # Ties: keep the older one (added first, the one people know).
    keep, merge = (
        (a, b)
        if (score_a, -a.created_at.timestamp())
        >= (
            score_b,
            -b.created_at.timestamp(),
        )
        else (b, a)
    )
    kept_merits = merits_a if keep is a else merits_b
    other = {reason for _, reason in (merits_b if keep is a else merits_a)}
    why = [r for w, r in kept_merits if w > 0 and r and r not in other]
    if not why:
        why = ["added first"]
    can_merge = True
    if not access.can_write_item(merge):
        if access.can_write_item(keep):
            # Only the other one can go: merge the other way round.
            keep, merge = merge, keep
            why = ["you can change only the other one"]
        else:
            can_merge = False
            why = ["you may not change either (reader)"]
    return Pair(keep=keep, merge=merge, reasons=reasons, why=why, can_merge=can_merge)


def dismiss(db: Session, a: uuid.UUID, b: uuid.UUID, user_id: uuid.UUID) -> None:
    """Remember that the two are different papers."""
    first, second = sorted((a, b))
    db.execute(
        insert(NotDuplicate)
        .values(item_a=first, item_b=second, decided_by=user_id)
        .on_conflict_do_nothing()
    )


# Titles less alike than this (two words shared of seven and three) are
# not suggested.
ALIKE = 0.5


def title_words(
    title: ColumnElement[str] | InstrumentedAttribute[str],
) -> ColumnElement[list[str]]:
    """A title's words as Postgres reads English: stems, without stop words
    or markup (as the index ``ix_items_title_words`` has them)."""
    english = literal_column("'english'::regconfig")
    return func.tsvector_to_array(func.to_tsvector(english, title))


def titled_alike(db: Session, access: Access, item: Item, limit: int = 8) -> list[Item]:
    """Papers the person can see whose titles share words with this one's,
    the most alike first: at least two words shared (all, for a shorter
    title), scored by how many of both titles' words are shared (Dice), at
    least ALIKE.
    "Code of Spin qubits" finds "Spin qubits"."""
    mine = set(db.scalar(select(title_words(literal(item.title)))) or [])
    if not mine:
        return []
    theirs = title_words(Item.title)
    rows = db.execute(
        select(Item.id, theirs).where(
            Item.id != item.id,
            Item.deleted_at.is_(None),
            access.item_filter(),
            theirs.op("&&")(cast(sorted(mine), ARRAY(Text))),
        )
    ).all()
    scored = []
    for other_id, words in rows:
        other = set(words)
        shared = len(mine & other)
        score = 2 * shared / (len(mine) + len(other))
        if shared >= min(2, len(mine), len(other)) and score >= ALIKE:
            scored.append((score, other_id))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    best = [other_id for _, other_id in scored[:limit]]
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(best)))}
    return [items[i] for i in best]
