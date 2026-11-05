"""Backups, for site administrators (restoring is on the command line)."""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from paperus import backup, system
from paperus.api.admin import Admin
from paperus.api.deps import DB
from paperus.jobs import queue_backup

router = APIRouter(prefix="/api/admin/backups", tags=["backups"])


class BackupOut(BaseModel):
    name: str
    created_at: str
    paperus_version: str
    with_files: bool
    files: int
    size: int
    """Bytes of the backup itself (files are kept once for all backups)."""
    items: int


class Backups(BaseModel):
    path: str
    """Where the server writes backups."""
    files_size: int
    """Bytes of the files kept for all backups together."""
    backups: list[BackupOut]
    config: system.BackupConfig


class BackupRequest(BaseModel):
    with_files: bool = True


def _out(manifest: backup.Manifest) -> BackupOut:
    items = manifest.tables.get("items")
    return BackupOut(
        name=manifest.name,
        created_at=manifest.created_at,
        paperus_version=manifest.paperus_version,
        with_files=manifest.with_files,
        files=manifest.files,
        size=manifest.size,
        items=items.rows if items else 0,
    )


@router.get("")
def list_backups(request: Request, db: DB, admin: Admin) -> Backups:
    root = request.app.state.settings.backup_path
    pool = root / "files"
    files_size = (
        sum(p.stat().st_size for p in pool.rglob("*") if p.is_file())
        if pool.is_dir()
        else 0
    )
    return Backups(
        path=str(root.resolve()),
        files_size=files_size,
        backups=[_out(m) for m in backup.list_backups(root)],
        config=system.load_backup_config(db),
    )


@router.post("", status_code=202)
def start_backup(body: BackupRequest, request: Request, admin: Admin) -> Response:
    """Queue a backup now (the worker writes it); 409 if one is running."""
    if not queue_backup(request.app.state.jobs, with_files=body.with_files):
        raise HTTPException(409, "a backup is queued or running already")
    return Response(status_code=202)


@router.put("/config")
def set_backup_config(
    body: system.BackupConfig, db: DB, admin: Admin
) -> system.BackupConfig:
    system.save_backup_config(db, body)
    db.commit()
    return body


@router.delete("/{name}", status_code=204)
def delete_backup(name: str, request: Request, admin: Admin) -> Response:
    try:
        backup.delete_backup(request.app.state.settings.backup_path, name)
    except backup.BackupError as error:
        raise HTTPException(404, str(error)) from error
    return Response(status_code=204)
