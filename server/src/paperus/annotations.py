"""Annotations: a person's highlights, underlines, strike-throughs, sticky
notes, words written on the page, areas and pen strokes on a file's pages,
each with a colour, a comment and tags (as in Zotero; each kind a standard
PDF annotation, so they can be written into a PDF). Positions are PDF points
from the page's lower left, as in the PDF itself.

Who sees them: their person always; others who may read the paper only if
the person shares their annotations of that paper (``AnnotationShare``,
"Share my annotations with the group"). Only their person changes them.

A PDF's own annotations (made in another reader) are taken in once, when the
file is read, as annotations of the person who uploaded it
(``Annotation.imported``), and where each sat is kept (``File.file_marks``):
the viewer draws the pages without those for whoever sees the uploader's
annotations (also after one of them was deleted), and as the file has them
for others. Annotations of kinds paperus does not know stay in the PDF.
"""

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from paperus import changes
from paperus.models import (
    Annotation,
    AnnotationKind,
    AnnotationShare,
    File,
    Item,
    Version,
)

# Zotero's colours: yellow, red, green, blue, purple, magenta, orange, grey.
COLORS = [
    "#ffd400",
    "#ff6666",
    "#5fb236",
    "#2ea8e5",
    "#a28ae5",
    "#e56eee",
    "#f19837",
    "#aaaaaa",
]
_COLOR = re.compile(r"^#[0-9a-f]{6}$")
# Bounds against absurd input (a page is at most 14400 points wide).
MAX_POINT = 100_000.0
MAX_RECTS = 1000
MAX_NUMBERS = 20_000

# Kinds that mark text (the text they mark is kept with them).
TEXT_KINDS = {
    AnnotationKind.HIGHLIGHT,
    AnnotationKind.UNDERLINE,
    AnnotationKind.STRIKEOUT,
}


class Position(BaseModel):
    """Where on the page: ``rects`` (x1, y1, x2, y2 each) for every kind but
    ink, ``paths`` (x, y pairs) with a ``width`` for ink; ``font_size`` for
    words written on the page; ``rotation`` (degrees) of a sticky note or
    written words, as PDF annotations have."""

    rects: list[list[float]] = Field(default_factory=list, max_length=MAX_RECTS)
    paths: list[list[float]] = Field(default_factory=list, max_length=MAX_RECTS)
    width: float | None = Field(None, gt=0, le=100)
    font_size: float | None = Field(None, gt=0, le=200)
    rotation: int = Field(0, ge=0, lt=360)

    @field_validator("rects")
    @classmethod
    def _rects(cls, rects: list[list[float]]) -> list[list[float]]:
        for rect in rects:
            if len(rect) != 4 or any(abs(v) > MAX_POINT for v in rect):
                raise ValueError("a rect is [x1, y1, x2, y2] within the page")
        return [[round(v, 3) for v in rect] for rect in rects]

    @field_validator("paths")
    @classmethod
    def _paths(cls, paths: list[list[float]]) -> list[list[float]]:
        if sum(len(p) for p in paths) > MAX_NUMBERS:
            raise ValueError("too many points")
        for path in paths:
            if len(path) < 2 or len(path) % 2 or any(abs(v) > MAX_POINT for v in path):
                raise ValueError("a path is x, y pairs within the page")
        return [[round(v, 2) for v in path] for path in paths]


class AnnotationIn(BaseModel):
    kind: AnnotationKind
    page_index: int = Field(ge=0, le=100_000)
    page_label: str | None = Field(None, max_length=32)
    position: Position
    color: str = COLORS[0]
    text: str | None = Field(None, max_length=20_000)
    comment: str | None = Field(None, max_length=20_000)
    tags: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("color")
    @classmethod
    def _color(cls, color: str) -> str:
        color = color.lower()
        if not _COLOR.match(color):
            raise ValueError("a colour is #rrggbb")
        return color

    @field_validator("tags")
    @classmethod
    def _tags(cls, tags: list[str]) -> list[str]:
        cleaned = [" ".join(t.split())[:100] for t in tags]
        return list(dict.fromkeys(t for t in cleaned if t))

    @model_validator(mode="after")
    def _shape(self) -> "AnnotationIn":
        if self.kind == AnnotationKind.INK:
            if not self.position.paths or not self.position.width:
                raise ValueError("a pen stroke needs paths and a width")
        elif not self.position.rects:
            raise ValueError("this kind needs rects")
        return self


def visible(user_id: uuid.UUID, item_id: uuid.UUID) -> Any:  # noqa: ANN401 (SQL)
    """Condition: annotations the person sees on a paper they may read:
    their own, and those of people who share theirs of this paper."""
    sharing = select(AnnotationShare.user_id).where(AnnotationShare.item_id == item_id)
    return or_(Annotation.user_id == user_id, Annotation.user_id.in_(sharing))


def of_file(db: Session, user_id: uuid.UUID, file: File) -> list[Annotation]:
    """The file's annotations the person sees, in reading order (by page,
    then from the top of the page)."""
    found = list(
        db.scalars(
            select(Annotation).where(
                Annotation.file_id == file.id,
                visible(user_id, file.version.item_id),
            )
        )
    )
    return sorted(found, key=reading_order)


def reading_order(annotation: Annotation) -> tuple[int, float, float]:
    rects = annotation.position.get("rects") or []
    paths = annotation.position.get("paths") or []
    ys = [max(r[1], r[3]) for r in rects] + [v for p in paths for v in p[1::2]]
    xs = [min(r[0], r[2]) for r in rects] + [v for p in paths for v in p[0::2]]
    return (annotation.page_index, -max(ys, default=0), min(xs, default=0))


def shares(db: Session, user_id: uuid.UUID, item_id: uuid.UUID) -> bool:
    return db.get(AnnotationShare, (user_id, item_id)) is not None


def share(db: Session, user_id: uuid.UUID, item: Item, shared: bool) -> None:
    """Show (or stop showing) the person's annotations of the paper to those
    who may read it. Does not commit."""
    found = db.get(AnnotationShare, (user_id, item.id))
    if shared == (found is not None):
        return
    if shared:
        db.add(AnnotationShare(user_id=user_id, item_id=item.id))
    else:
        db.delete(found)
    # For syncing: the annotations come into others' reach, or leave it
    # (their author keeps them: changed after removed).
    files = select(File.id).join(Version).where(Version.item_id == item.id)
    mine = (Annotation.user_id == user_id, Annotation.file_id.in_(files))
    ids = db.scalars(
        update(Annotation)
        .where(*mine)
        .values(change=changes.change_number(db))
        .returning(Annotation.id)
    ).all()
    if not shared:
        changes.removed(db, "annotation", [(i, item.library_id) for i in ids])


def hidden_marks(db: Session, user_id: uuid.UUID, file: File) -> list[dict[str, Any]]:
    """The PDF's own annotations the viewer leaves out when drawing the
    pages ({page_index, rect}): those taken in, if the person sees the
    uploader's annotations (their own, or shared)."""
    if not file.file_marks or file.uploaded_by is None:
        return []
    uploader = file.uploaded_by
    if uploader == user_id or shares(db, uploader, file.version.item_id):
        return file.file_marks
    return []


# Defaults for annotations whose PDF gives no colour (as most readers draw).
_DEFAULT_COLORS = {AnnotationKind.TEXT: "#000000", AnnotationKind.INK: "#ff6666"}


def _color_of(kind: AnnotationKind, color: str | None) -> str:
    """The PDF's colour; black or none means "unset" for marks that are
    never black (yellow, as other readers show them)."""
    if color and (color != "#000000" or kind in _DEFAULT_COLORS):
        return color
    return _DEFAULT_COLORS.get(kind, COLORS[0])


def take_in(db: Session, file: File, found: list[dict[str, Any]]) -> int:
    """The PDF's own annotations (``paperus.pdf.annotations``) as its
    uploader's, once; where each sat is kept. Annotations without enough to
    show (words on the page without words) stay in the PDF. Does not commit.
    Returns how many were taken in."""
    if file.file_marks is not None or file.uploaded_by is None:
        return 0
    marks = []
    for entry in found:
        kind = AnnotationKind(entry["kind"])
        if kind == AnnotationKind.TEXT and not entry.get("text"):
            continue
        position: dict[str, Any] = {}
        for key in ("rects", "paths", "width", "font_size"):
            if entry.get(key):
                position[key] = entry[key]
        db.add(
            Annotation(
                file_id=file.id,
                user_id=file.uploaded_by,
                kind=kind,
                page_index=entry["page_index"],
                page_label=(entry.get("page_label") or None),
                position=position,
                color=_color_of(kind, entry.get("color")),
                text=entry.get("text"),
                comment=entry.get("comment"),
                imported=True,
            )
        )
        marks.append({"page_index": entry["page_index"], "rect": entry["rect"]})
    file.file_marks = marks
    return len(marks)
