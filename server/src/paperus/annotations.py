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
(``Annotation.imported``); the viewer then draws the pages without them for
those who see these, and as the file has them for others.
"""

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from paperus.models import Annotation, AnnotationKind, AnnotationShare, File, Item

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
    if shared and found is None:
        db.add(AnnotationShare(user_id=user_id, item_id=item.id))
    elif not shared and found is not None:
        db.delete(found)


def file_marks_hidden(db: Session, user_id: uuid.UUID, file: File) -> bool:
    """Whether the viewer draws the pages without the PDF's own annotations:
    they were taken in, and the person sees them (their own, or shared)."""
    if not file.annotations_read or file.uploaded_by is None:
        return False
    return file.uploaded_by == user_id or shares(
        db, file.uploaded_by, file.version.item_id
    )
