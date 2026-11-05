"""Admin page: settings, the ML service, progress and jobs."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text

from paperus import system
from paperus.api.deps import DB, CurrentUser
from paperus.jobs import queue_embedding_sweep, queue_text_sweep
from paperus.ml import MLClient, MLUnavailable
from paperus.models import Chunk, Embedding, File, FileChunk, Item, TextStatus, User
from paperus.processing import reread_all

router = APIRouter(prefix="/api/admin", tags=["admin"])


def current_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(403, "admins only")
    return user


Admin = Annotated[User, Depends(current_admin)]


class MLService(BaseModel):
    url: str
    ok: bool
    error: str | None


class MLModel(BaseModel):
    name: str
    task: str
    dimensions: int
    max_tokens: int
    loaded: bool
    cached_bytes: int | None


class MLStatus(BaseModel):
    services: list[MLService]
    models: list[MLModel]
    """Empty if no service answers."""


class Stats(BaseModel):
    items: int
    files: int
    files_pending: int
    """Files whose text (and, for uploads, metadata) is still being read."""
    chunks: int
    """Passages searchable by meaning (reference lists are left out)."""
    embedded: int
    """Chunks with a vector from the current embedding model."""
    embedding_model: str
    jobs: dict[str, dict[str, int]]
    """Background jobs per queue and status (todo, doing, failed, …)."""


def _ml(request: Request) -> MLClient:
    ml: MLClient = request.app.state.ml
    return ml


def _models(ml: MLClient) -> list[MLModel]:
    return [MLModel.model_validate(m) for m in ml.models()]


@router.get("/config")
def get_config(request: Request, db: DB, admin: Admin) -> system.SystemConfig:
    return system.load_config(db, request.app.state.settings)


@router.put("/config")
def set_config(
    body: system.SystemConfig, request: Request, db: DB, admin: Admin
) -> system.SystemConfig:
    """Save settings. A new embedding model must be one the ML service
    offers; the library is then re-embedded in the background, while keyword
    search keeps working and search by meaning covers more and more."""
    current = system.load_config(db, request.app.state.settings)
    model_changed = body.embedding_model != current.embedding_model
    if model_changed:
        try:
            known = {m.name for m in _models(_ml(request)) if m.task == "embedding"}
        except MLUnavailable as error:
            raise HTTPException(
                503, "ML service unreachable; cannot check the model"
            ) from error
        if body.embedding_model not in known:
            raise HTTPException(
                422, f"the ML service has no model {body.embedding_model!r}"
            )
    system.save_config(db, body)
    db.commit()
    if model_changed:
        queue_embedding_sweep(request.app.state.jobs)
    return body


@router.get("/ml")
def ml_status(request: Request, admin: Admin) -> MLStatus:
    ml = _ml(request)
    services = [MLService(url=u, ok=e is None, error=e) for u, e in ml.status()]
    try:
        models = _models(ml)
    except MLUnavailable:
        models = []
    return MLStatus(services=services, models=models)


@router.delete("/ml/models/{name}", status_code=204)
def delete_ml_model(name: str, request: Request, db: DB, admin: Admin) -> None:
    """Remove a downloaded model from the ML service (not the one in use)."""
    if name == system.load_config(db, request.app.state.settings).embedding_model:
        raise HTTPException(409, "this model is in use")
    try:
        _ml(request).delete_model(name)
    except MLUnavailable as error:
        raise HTTPException(503, "ML service unreachable") from error


@router.get("/stats")
def stats(request: Request, db: DB, admin: Admin) -> Stats:
    model = system.load_config(db, request.app.state.settings).embedding_model
    # Passages to embed: in files not in the trash, outside reference lists.
    visible_chunks = (
        select(FileChunk.chunk_sha256)
        .join(File, File.id == FileChunk.file_id)
        .where(File.deleted_at.is_(None), FileChunk.in_references.is_(False))
    )
    jobs: dict[str, dict[str, int]] = {}
    for queue, status, count in db.execute(
        text(
            "SELECT queue_name, status::text, count(*) FROM procrastinate_jobs"
            " GROUP BY queue_name, status"
        )
    ):
        jobs.setdefault(queue, {})[status] = count
    count = func.count()
    return Stats(
        items=db.scalar(
            select(count).select_from(Item).where(Item.deleted_at.is_(None))
        )
        or 0,
        files=db.scalar(
            select(count).select_from(File).where(File.deleted_at.is_(None))
        )
        or 0,
        files_pending=db.scalar(
            select(count)
            .select_from(File)
            .where(File.text_status == TextStatus.PENDING, File.deleted_at.is_(None))
        )
        or 0,
        chunks=db.scalar(
            select(func.count(func.distinct(Chunk.sha256))).where(
                Chunk.sha256.in_(visible_chunks)
            )
        )
        or 0,
        embedded=db.scalar(
            select(count)
            .select_from(Embedding)
            .where(Embedding.model == model, Embedding.chunk_sha256.in_(visible_chunks))
        )
        or 0,
        embedding_model=model,
        jobs=jobs,
    )


@router.post("/jobs/{job}", status_code=202)
def run_job(job: str, request: Request, db: DB, admin: Admin) -> dict[str, Any]:
    """Start a sweep now: ``embeddings`` (embed what is missing), ``text``
    (read files still pending), or ``text-all`` (read every file again)."""
    sweeps = {"embeddings": queue_embedding_sweep, "text": queue_text_sweep}
    if job == "text-all":
        count = reread_all(db)
        queue_text_sweep(request.app.state.jobs)
        return {"queued": job, "files": count}
    if job not in sweeps:
        raise HTTPException(404, f"unknown job {job!r}")
    sweeps[job](request.app.state.jobs)
    return {"queued": job}
