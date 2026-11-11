"""Annotations on a file's pages (``paperus.annotations``): listed with the
file, made and changed by their person, shared per paper."""

import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from paperus import annotations, pdf
from paperus.access import Access
from paperus.annotations import AnnotationIn, Position
from paperus.api.deps import DB, CurrentAccess, IfMatch, check_unchanged
from paperus.api.ids import NewId, new_id, sent_again
from paperus.api.items import get_readable_item
from paperus.models import Annotation, AnnotationKind, File, User

router = APIRouter(tags=["annotations"])


class AnnotationOut(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    kind: AnnotationKind
    page_index: int
    """From 0."""
    page_label: str | None
    position: dict[str, Any]
    """PDF points from the page's lower left: ``rects`` [[x1, y1, x2, y2]],
    or ``paths`` [[x, y, …]] with ``width``; ``font_size``, ``rotation``."""
    color: str
    text: str | None
    comment: str | None
    tags: list[str]
    imported: bool
    """Taken in from the PDF itself."""
    mine: bool
    author: str
    """Who made it (display name, else username)."""
    created_at: datetime
    changed_at: datetime
    change: int
    """For ``If-Match`` when changing it."""


class FileAnnotations(BaseModel):
    annotations: list[AnnotationOut]
    """Those the person sees, in reading order."""
    hidden_marks: list[dict[str, Any]]
    """The PDF's own annotations to leave out when drawing its pages
    ({page_index, rect}: taken in, among these)."""
    shared: bool
    """The person shares their annotations of this paper."""
    can_share: bool
    """The paper belongs to a group (others may read it)."""
    colors: list[str] = annotations.COLORS


class NewAnnotation(AnnotationIn):
    id: NewId = None


class AnnotationChange(BaseModel):
    color: str | None = None
    comment: str | None = Field(None, max_length=20_000)
    text: str | None = Field(None, max_length=20_000)
    tags: list[str] | None = None
    position: Position | None = None
    page_label: str | None = Field(None, max_length=32)


class Sharing(BaseModel):
    shared: bool


def _file(db: Session, access: Access, file_id: uuid.UUID) -> File:
    file = db.get(File, file_id)
    if file is None or not access.can_read_item(file.version.item):
        raise HTTPException(404, "file not found")
    return file


def _name(db: Session, user_id: uuid.UUID, cache: dict[uuid.UUID, str]) -> str:
    if user_id not in cache:
        user = db.get(User, user_id)
        cache[user_id] = (user.display_name or user.username) if user else "someone"
    return cache[user_id]


def annotation_out(
    db: Session, access: Access, annotation: Annotation, names: dict[uuid.UUID, str]
) -> AnnotationOut:
    return AnnotationOut(
        id=annotation.id,
        file_id=annotation.file_id,
        kind=AnnotationKind(annotation.kind),
        page_index=annotation.page_index,
        page_label=annotation.page_label,
        position=annotation.position,
        color=annotation.color,
        text=annotation.text,
        comment=annotation.comment,
        tags=annotation.tags,
        imported=annotation.imported,
        mine=annotation.user_id == access.user.id,
        author=_name(db, annotation.user_id, names),
        created_at=annotation.created_at,
        changed_at=annotation.changed_at,
        change=annotation.change,
    )


@router.get("/api/files/{file_id}/annotations")
def file_annotations(
    file_id: uuid.UUID, db: DB, access: CurrentAccess
) -> FileAnnotations:
    """The file's annotations the person sees: their own, and those others
    share of this paper."""
    file = _file(db, access, file_id)
    item = file.version.item
    names: dict[uuid.UUID, str] = {}
    return FileAnnotations(
        annotations=[
            annotation_out(db, access, a, names)
            for a in annotations.of_file(db, access.user.id, file)
        ],
        hidden_marks=annotations.hidden_marks(db, access.user.id, file),
        shared=annotations.shares(db, access.user.id, item.id),
        can_share=item.library_id in access.group_libraries.values(),
    )


@router.post("/api/files/{file_id}/annotations", status_code=201)
def add_annotation(
    file_id: uuid.UUID, body: NewAnnotation, db: DB, access: CurrentAccess
) -> AnnotationOut:
    """A new annotation of the person's (anyone who may read the paper may
    annotate it, readers too)."""
    again = sent_again(db, Annotation, body.id, lambda a: a.user_id == access.user.id)
    if again is not None:
        return annotation_out(db, access, again, {})
    file = _file(db, access, file_id)
    if file.deleted_at is not None or file.version.item.deleted_at is not None:
        raise HTTPException(409, "the file is in the trash")
    annotation = Annotation(
        **new_id(body.id),
        file_id=file.id,
        user_id=access.user.id,
        kind=body.kind,
        page_index=body.page_index,
        page_label=body.page_label,
        position=body.position.model_dump(exclude_defaults=True),
        color=body.color,
        text=body.text,
        comment=body.comment,
        tags=body.tags,
    )
    db.add(annotation)
    db.commit()
    return annotation_out(db, access, annotation, {})


def _own(db: Session, access: Access, annotation_id: uuid.UUID) -> Annotation:
    """One of the person's annotations on a paper they may still read."""
    annotation = db.get(Annotation, annotation_id)
    if annotation is None or annotation.user_id != access.user.id:
        raise HTTPException(404, "annotation not found")
    _file(db, access, annotation.file_id)
    return annotation


@router.patch("/api/annotations/{annotation_id}")
def change_annotation(
    annotation_id: uuid.UUID,
    body: AnnotationChange,
    db: DB,
    access: CurrentAccess,
    if_match: IfMatch = None,
) -> AnnotationOut:
    """Change one's annotation: only the fields given (an empty comment
    removes it). With ``If-Match``, 412 if it changed since."""
    annotation = _own(db, access, annotation_id)
    check_unchanged(if_match, annotation.change)
    given = body.model_fields_set
    checked = AnnotationIn(
        kind=AnnotationKind(annotation.kind),
        page_index=annotation.page_index,
        page_label=body.page_label if "page_label" in given else annotation.page_label,
        position=body.position or Position(**annotation.position),
        color=body.color or annotation.color,
        text=body.text if "text" in given else annotation.text,
        comment=body.comment if "comment" in given else annotation.comment,
        tags=body.tags if body.tags is not None else annotation.tags,
    )
    annotation.page_label = checked.page_label
    annotation.position = checked.position.model_dump(exclude_defaults=True)
    annotation.color = checked.color
    annotation.text = checked.text or None
    annotation.comment = checked.comment or None
    annotation.tags = checked.tags
    annotation.changed_at = datetime.now(UTC)
    db.commit()
    return annotation_out(db, access, annotation, {})


@router.delete("/api/annotations/{annotation_id}", status_code=204)
def delete_annotation(annotation_id: uuid.UUID, db: DB, access: CurrentAccess) -> None:
    db.delete(_own(db, access, annotation_id))
    db.commit()


@router.put("/api/items/{item_id}/annotation-sharing")
def share_annotations(
    item_id: uuid.UUID, body: Sharing, db: DB, access: CurrentAccess
) -> Sharing:
    """Show one's annotations of the paper to everyone who may read it (or
    stop)."""
    item = get_readable_item(db, access, item_id)
    annotations.share(db, access.user.id, item, body.shared)
    db.commit()
    return body


@router.get("/api/files/{file_id}/annotated")
def annotated_file(
    file_id: uuid.UUID, request: Request, db: DB, access: CurrentAccess
) -> Response:
    """The PDF with the annotations the person sees written in, as standard
    PDF annotations any reader shows (the PDF's own that were taken in are
    replaced, not doubled)."""
    file = _file(db, access, file_id)
    if file.media_type != "application/pdf":
        raise HTTPException(422, "only PDFs take annotations")
    added = [
        {
            "kind": a.kind,
            "page_index": a.page_index,
            "position": a.position,
            "color": a.color,
            "text": a.text,
            "comment": a.comment,
        }
        for a in annotations.of_file(db, access.user.id, file)
    ]
    removed = annotations.hidden_marks(db, access.user.id, file)
    with (
        request.app.state.blobs.local_file(file.blob_sha256) as path,
        tempfile.TemporaryDirectory() as folder,
    ):
        out = Path(folder) / "annotated.pdf"
        try:
            pdf.with_annotations(path, out, added, removed)
        except pdf.PdfError as error:
            raise HTTPException(422, "the PDF could not be written") from error
        data = out.read_bytes()
    stem = file.filename.removesuffix(".pdf").removesuffix(".PDF")
    name = f"{stem} (annotated).pdf"
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(name)}",
            "X-Content-Type-Options": "nosniff",
        },
    )
