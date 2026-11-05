"""Admin page: settings, the ML service, progress and jobs."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from paperus import integrity, metrics, system
from paperus.api.deps import DB, CurrentUser
from paperus.jobs import (
    queue_embedding_sweep,
    queue_empty_trash,
    queue_integrity_check,
    queue_ml_configuration,
    queue_text_sweep,
)
from paperus.ml import MLClient, MLLoading, MLRejected, MLUnavailable
from paperus.models import User
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
    # For choosing (older ML services do not send these).
    description: str = ""
    licence: str = ""
    download_mb: int = 0
    scores: dict[str, float] = {}
    """Published retrieval scores (nDCG@10, out of 100), by benchmark."""
    benchmarks: dict[str, str] = {}
    """What the keys of ``scores`` mean."""


class MLSpeed(BaseModel):
    model: str
    loading: bool = False
    """The model is still downloading or loading: ask again in a while."""
    passages: int = 0
    seconds: float = 0
    passages_per_second: float = 0
    url: str | None = None
    """The ML service that measured it."""


class MLServiceState(BaseModel):
    url: str
    threads: int
    keep: list[str]
    cores: int
    """CPU cores this ML service may use."""
    loaded: list[str]
    loading: list[str] = []


class MLStatus(BaseModel):
    services: list[MLService]
    models: list[MLModel]
    """Empty if no service answers."""
    service: MLServiceState | None = None
    """The first service's settings and cores (None for older services)."""


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
        except (MLUnavailable, MLRejected) as error:
            raise HTTPException(
                503, "ML service unreachable; cannot check the model"
            ) from error
        if body.embedding_model not in known:
            raise HTTPException(
                422, f"the ML service has no model {body.embedding_model!r}"
            )
    system.save_config(db, body)
    db.commit()
    system.apply(body, request.app.state.http)
    if model_changed:
        queue_embedding_sweep(request.app.state.jobs)
    if model_changed or body.ml_threads != current.ml_threads:
        # The worker sends it at once (first in its queue), and every minute.
        queue_ml_configuration(request.app.state.jobs)
    return body


@router.get("/ml")
def ml_status(request: Request, admin: Admin) -> MLStatus:
    ml = _ml(request)
    services = [MLService(url=u, ok=e is None, error=e) for u, e in ml.status()]
    try:
        models = _models(ml)
    except (MLUnavailable, MLRejected):
        models = []
    try:
        service = MLServiceState.model_validate(ml.service_config())
    except (MLUnavailable, MLRejected, ValueError):
        service = None
    return MLStatus(services=services, models=models, service=service)


@router.post("/ml/models/{name}/speed")
def measure_ml_speed(name: str, request: Request, admin: Admin) -> MLSpeed:
    """Time a model on this installation's ML service with sample passages.
    A model not downloaded yet starts downloading: the answer then says
    ``loading``; ask again in a while."""
    try:
        return MLSpeed.model_validate(_ml(request).measure_speed(name))
    except MLLoading:
        return MLSpeed(model=name, loading=True)
    except MLRejected as error:
        raise HTTPException(
            404 if error.status == 404 else 502, error.detail
        ) from error
    except MLUnavailable as error:
        raise HTTPException(503, f"ML service unreachable: {error}") from error


@router.delete("/ml/models/{name}", status_code=204)
def delete_ml_model(name: str, request: Request, db: DB, admin: Admin) -> None:
    """Remove a downloaded model from the ML service (not the one in use)."""
    if name == system.load_config(db, request.app.state.settings).embedding_model:
        raise HTTPException(409, "this model is in use")
    try:
        _ml(request).delete_model(name)
    except MLRejected as error:
        raise HTTPException(404, error.detail) from error
    except MLUnavailable as error:
        raise HTTPException(503, "ML service unreachable") from error


@router.get("/stats")
def stats(request: Request, db: DB, admin: Admin) -> Stats:
    figures = metrics.library_figures(db, request.app.state.settings)
    return Stats(
        items=figures.items,
        files=figures.files,
        files_pending=figures.files_pending,
        chunks=figures.chunks,
        embedded=figures.embedded,
        embedding_model=figures.embedding_model,
        jobs=figures.jobs,
    )


@router.post("/jobs/{job}", status_code=202)
def run_job(job: str, request: Request, db: DB, admin: Admin) -> dict[str, Any]:
    """Start a sweep now: ``embeddings`` (embed what is missing), ``text``
    (read files still pending), ``text-all`` (read every file again),
    ``trash`` (delete what is older than the trash days), ``integrity``
    (check stored contents), ``integrity-deep`` (also their SHA-256) or
    ``integrity-clean`` (check and remove unused stored contents)."""
    jobs = request.app.state.jobs
    sweeps = {
        "embeddings": queue_embedding_sweep,
        "text": queue_text_sweep,
        "trash": queue_empty_trash,
        "integrity": queue_integrity_check,
        "integrity-deep": lambda app: queue_integrity_check(app, deep=True),
        "integrity-clean": lambda app: queue_integrity_check(app, remove_unused=True),
    }
    if job == "text-all":
        count = reread_all(db)
        queue_text_sweep(request.app.state.jobs)
        return {"queued": job, "files": count}
    if job not in sweeps:
        raise HTTPException(404, f"unknown job {job!r}")
    sweeps[job](jobs)
    return {"queued": job}


@router.get("/integrity")
def integrity_report(db: DB, admin: Admin) -> integrity.Report | None:
    """The last integrity check's report (None before the first)."""
    return integrity.last_report(db)
