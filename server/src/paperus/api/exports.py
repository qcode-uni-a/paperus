"""Exports of what a person can see (Settings → Export): asked for here,
written by the worker, each zip downloaded from when it is written, for a
day. See ``paperus.export`` and docs/export.md."""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from paperus import export
from paperus.access import Access
from paperus.api.auth import public_base
from paperus.api.deps import DB, CurrentAccess
from paperus.jobs import queue_export
from paperus.models import Collection, Export, ExportStatus
from paperus.system import load_config

router = APIRouter(prefix="/api/exports", tags=["exports"])


class ExportPartOut(BaseModel):
    part: int
    """From 1."""
    name: str
    """The zip's file name."""
    size: int
    files: int


class ExportOut(BaseModel):
    id: uuid.UUID
    status: ExportStatus
    options: export.Options
    collection_name: str | None
    """The collection exported, if only one."""
    done: int
    total: int
    size: int | None
    parts: list[ExportPartOut]
    """Its zips, each as soon as it is written."""
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None
    """Until when it can be downloaded."""


def export_out(record: Export, collection_name: str | None = None) -> ExportOut:
    return ExportOut(
        id=record.id,
        status=ExportStatus(record.status),
        options=export.Options.model_validate(record.options),
        collection_name=collection_name,
        done=record.done,
        total=record.total,
        size=record.size,
        parts=[ExportPartOut(part=n, **part) for n, part in enumerate(record.parts, 1)],
        error=record.error,
        created_at=record.created_at,
        finished_at=record.finished_at,
        expires_at=record.expires_at,
    )


def _checked(db: DB, access: Access, options: export.Options) -> export.Options:
    """The options, if the person sees what they name."""
    if options.owners is not None:
        if not options.owners:
            raise HTTPException(422, "choose at least one owner")
        if not all(access.can_read(owner) for owner in options.owners):
            raise HTTPException(404, "owner not found")
    if options.collection_id is not None:
        collection = db.get(Collection, options.collection_id)
        if collection is None or not access.can_read(collection.library_id):
            raise HTTPException(404, "collection not found")
    return options


@router.post("/estimate")
def estimate_export(
    body: export.Options, db: DB, access: CurrentAccess
) -> export.Estimate:
    """How much an export with these options would hold, and its size."""
    return export.estimate(db, access, _checked(db, access, body))


@router.post("", status_code=201)
def start_export(
    body: export.Options, request: Request, db: DB, access: CurrentAccess
) -> ExportOut:
    """Export what the person sees (by default everything, with files).
    Written in the background; poll ``GET /api/exports/{id}``, or wait for
    the notifications (one per zip written)."""
    options = _checked(db, access, body)
    record = Export(
        user_id=access.user.id,
        status=ExportStatus.WAITING,
        options=options.model_dump(mode="json"),
        parts=[],
    )
    db.add(record)
    db.commit()
    queue_export(request.app.state.jobs, record.id, access.user.id)
    return export_out(record, _collection_names(db, [record]).get(record.id))


def _collection_names(db: DB, records: list[Export]) -> dict[uuid.UUID, str]:
    wanted = {
        uuid.UUID(str(r.options["collection_id"])): r.id
        for r in records
        if r.options.get("collection_id")
    }
    return {
        wanted[collection_id]: name
        for collection_id, name in db.execute(
            select(Collection.id, Collection.name).where(Collection.id.in_(wanted))
        )
    }


@router.get("")
def list_exports(db: DB, access: CurrentAccess) -> list[ExportOut]:
    """The person's exports, newest first."""
    records = list(
        db.scalars(
            select(Export)
            .where(Export.user_id == access.user.id)
            .order_by(Export.created_at.desc())
            .limit(20)
        )
    )
    names = _collection_names(db, records)
    return [export_out(record, names.get(record.id)) for record in records]


def _own(db: DB, access: Access, export_id: uuid.UUID) -> Export:
    record = db.get(Export, export_id)
    if record is None or record.user_id != access.user.id:
        raise HTTPException(404, "export not found")
    return record


@router.get("/{export_id}")
def get_export(export_id: uuid.UUID, db: DB, access: CurrentAccess) -> ExportOut:
    record = _own(db, access, export_id)
    return export_out(record, _collection_names(db, [record]).get(record.id))


@router.get(
    "/{export_id}/parts/{part}",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/zip": {}}},
        303: {"description": "Gone, followed in a browser: to the exports"},
    },
)
def download_export(
    export_id: uuid.UUID, part: int, request: Request, db: DB, access: CurrentAccess
) -> Response:
    """One zip of the export (from 1) once written, while it lasts; answers
    range requests (to read only the database out of part 1, say)."""
    settings = request.app.state.settings
    try:
        record = _own(db, access, export_id)
        path = export.part_path(settings, record, part)
        if path is None:
            raise HTTPException(404, "this export cannot be downloaded (any more)")
    except HTTPException:
        # A link followed (from a notification) after the export went: to
        # the list of exports rather than an error page.
        if "text/html" in request.headers.get("accept", ""):
            base = public_base(request, load_config(db, settings))
            return RedirectResponse(f"{base}/settings?open=export", status_code=303)
        raise
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.delete("/{export_id}", status_code=204)
def delete_export(
    export_id: uuid.UUID, request: Request, db: DB, access: CurrentAccess
) -> None:
    record = _own(db, access, export_id)
    if record.status == ExportStatus.RUNNING:
        raise HTTPException(409, "the export is being written; delete it when done")
    export.delete(db, request.app.state.settings, record)
    db.commit()
