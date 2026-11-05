"""First start: create the first administrator, or restore a backup.

Only while no user exists; afterwards these
answer 409. The database is empty then, so a restore needs no downtime.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from paperus import auth, backup
from paperus.api.auth import LoginResponse, set_session_cookie, user_out
from paperus.api.backups import BackupOut, backup_out
from paperus.api.deps import DB
from paperus.api.users import NewUser
from paperus.models import User

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupState(BaseModel):
    needed: bool
    """No user exists yet: the website shows the first-start page."""
    backup_path: str | None
    backups: list[BackupOut]
    """Backups found in the backup folder (only while setup is needed)."""


class RestoreRequest(BaseModel):
    name: str


class RestoreCheckOut(BaseModel):
    """Where the backup's files would come from. Files are stored by their
    SHA-256, so one already in the storage is the very same file: nothing
    is overwritten, missing ones are copied back, extra ones stay."""

    with_files: bool
    needed: int
    in_storage: int
    from_backup: int
    missing: int
    affected: list[str]
    affected_count: int
    extra: int | None


@router.get("/restore-check")
def check_restore(name: str, request: Request, db: DB) -> RestoreCheckOut:
    if not _needed(db):
        raise HTTPException(409, "paperus is set up already")
    state = request.app.state
    try:
        check = backup.check_restore(state.blobs, state.settings.backup_path, name)
    except backup.BackupError as error:
        raise HTTPException(404, str(error)) from error
    return RestoreCheckOut(
        with_files=check.with_files,
        needed=check.needed,
        in_storage=check.in_storage,
        from_backup=check.from_backup,
        missing=check.missing,
        affected=check.affected,
        affected_count=check.affected_count,
        extra=check.extra,
    )


def _needed(db: DB) -> bool:
    return not db.scalar(select(func.count()).select_from(User))


@router.get("")
def setup_state(request: Request, db: DB) -> SetupState:
    if not _needed(db):
        return SetupState(needed=False, backup_path=None, backups=[])
    root = request.app.state.settings.backup_path
    return SetupState(
        needed=True,
        backup_path=str(root.resolve()),
        backups=[backup_out(m) for m in backup.list_backups(root)],
    )


@router.post("/admin", status_code=201)
def create_first_admin(
    body: NewUser, request: Request, response: Response, db: DB
) -> LoginResponse:
    """The first administrator, logged in right away."""
    if not _needed(db):
        raise HTTPException(409, "paperus is set up already")
    user = auth.create_user(db, body.username, body.password, is_admin=True)
    token = auth.start_session(db, user)
    db.commit()
    set_session_cookie(request, response, token, auth.SESSION_LIFETIME.days)
    return LoginResponse(token=token, user=user_out(user))


@router.post("/restore", status_code=204)
def restore_on_first_start(body: RestoreRequest, request: Request, db: DB) -> Response:
    """Restore a backup from the backup folder into the empty database; then
    people log in with their accounts from the backup."""
    if not _needed(db):
        raise HTTPException(409, "paperus is set up already")
    db.close()
    state = request.app.state
    try:
        backup.restore_backup(
            state.settings,
            state.engine,
            state.blobs,
            state.settings.backup_path,
            body.name,
            replace=False,
        )
    except backup.BackupError as error:
        raise HTTPException(409, str(error)) from error
    # Connections may remember the old tables' layout.
    state.engine.dispose()
    return Response(status_code=204)
