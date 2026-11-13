"""Admin page: settings, the ML service, progress and jobs."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from paperus import auth, integrity, metrics, ocr, oidc, readable, system, usage
from paperus.access import Access
from paperus.api.auth import OIDC_CALLBACK, public_base
from paperus.api.deps import DB, CurrentUser, request_token
from paperus.jobs import (
    queue_author_linking,
    queue_embedding_sweep,
    queue_empty_trash,
    queue_errata_check,
    queue_integrity_check,
    queue_ml_configuration,
    queue_ocr_sweep,
    queue_published_check,
    queue_readable_copy,
    queue_reference_lists,
    queue_text_sweep,
    queue_tidy,
)
from paperus.ml import MLClient, MLLoading, MLRejected, MLUnavailable
from paperus.models import LoginSession, User
from paperus.processing import reread_all, reread_failed

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
    parameters: int = 0
    """Its size: how many weights (0: not published)."""
    released: str = ""
    """When it was published ("2024-01")."""
    recommended: bool = False
    """The one to use for its task where the ML service runs (on a CPU no
    reranker)."""
    memory_bytes: int | None = None
    """What it took once loaded on the ML service (RAM, or GPU memory there),
    as measured when it last loaded; None if never loaded there."""


class MLSpeed(BaseModel):
    model: str
    loading: bool = False
    """The model is still downloading or loading: ask again in a while."""
    passages: int = 0
    seconds: float = 0
    passages_per_second: float = 0
    url: str | None = None
    """The ML service that measured it."""


class MLGPU(BaseModel):
    name: str
    supported: bool
    """New enough for the GPU image (RTX 20xx generation or newer)."""


class MLMemory(BaseModel):
    total: int
    free: int
    """Bytes; free: available for new use."""


class MLServiceState(BaseModel):
    url: str
    threads: int
    keep: list[str]
    cores: int
    """CPU cores this ML service may use."""
    device: str = "cpu"
    """Where its models run: "cpu", or "cuda" (an NVIDIA GPU)."""
    loaded: list[str]
    loading: list[str] = []
    cuda_image: bool = False
    """It is the GPU image (``-cuda``)."""
    gpu_problem: str | None = None
    """Why its models run on the CPU."""
    gpus: list[MLGPU] = []
    """The NVIDIA cards of its machine, also those not passed to it."""
    driver: int | None = None
    """The NVIDIA driver's major version there, if one is loaded."""
    driver_needed: int = 580
    """The oldest driver the GPU image runs with."""
    ram: MLMemory | None = None
    """Its machine's RAM (older services do not say)."""
    gpu_memory: MLMemory | None = None
    """Its GPU's memory, on the GPU (all programs' use counted)."""
    on_cpu: dict[str, str] = {}
    """Models it runs on the CPU although it runs on the GPU, with why."""


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
    files_failed: int
    """Files whose text (and, for uploads, metadata) is still being read."""
    files_ocr: int = 0
    """Files whose scanned pages wait for OCR."""
    chunks: int
    """Passages searchable by meaning (reference lists are left out)."""
    embedded: int
    """Chunks with a vector from the current embedding model."""
    embedding_model: str
    jobs: dict[str, dict[str, int]]
    """Background jobs per queue and status (todo, doing, failed, …)."""
    storage: usage.Usage
    """Space the library and the backups take, and what is free."""


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
    rerank_changed = (body.rerank, body.rerank_model) != (
        current.rerank,
        current.rerank_model,
    )
    ocr_model_changed = body.ocr and body.ocr_model != current.ocr_model
    if model_changed or (rerank_changed and body.rerank != "off") or ocr_model_changed:
        try:
            known = [(m.name, m.task) for m in _models(_ml(request))]
        except (MLUnavailable, MLRejected) as error:
            raise HTTPException(
                503, "ML service unreachable; cannot check the model"
            ) from error
        if model_changed and (body.embedding_model, "embedding") not in known:
            raise HTTPException(
                422, f"the ML service has no model {body.embedding_model!r}"
            )
        if rerank_changed and (body.rerank_model, "rerank") not in known:
            raise HTTPException(
                422, f"the ML service has no reranker {body.rerank_model!r}"
            )
        if ocr_model_changed and (body.ocr_model, "ocr") not in known:
            raise HTTPException(
                422, f"the ML service has no OCR model {body.ocr_model!r}"
            )
    if body.ocr != current.ocr:
        ocr.switch(db, body.ocr)
    system.save_config(db, body)
    db.commit()
    system.apply(body, request.app.state.http)
    if model_changed:
        queue_embedding_sweep(request.app.state.jobs)
    if body.ocr and not current.ocr:
        queue_ocr_sweep(request.app.state.jobs)
    copy = ("copy_enabled", "copy_template", "copy_links")
    if body.copy_enabled and any(
        getattr(body, name) != getattr(current, name) for name in copy
    ):
        queue_readable_copy(request.app.state.jobs)
    if model_changed or rerank_changed or body.ml_threads != current.ml_threads:
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
        files_failed=figures.files_failed,
        files_ocr=figures.files_ocr,
        chunks=figures.chunks,
        embedded=figures.embedded,
        embedding_model=figures.embedding_model,
        jobs=figures.jobs,
        storage=usage.usage(db, request.app.state.settings),
    )


@router.post("/jobs/{job}", status_code=202)
def run_job(job: str, request: Request, db: DB, admin: Admin) -> dict[str, Any]:
    """Start a sweep now: ``embeddings`` (embed what is missing), ``text``
    (read files still pending), ``text-failed`` (try failed files again),
    ``text-all`` (read every file again), ``ocr`` (read scans waiting
    for OCR), ``published`` (look for preprints' published versions),
    ``references`` (look for papers' reference lists), ``errata`` (look
    for corrections to papers), ``authors`` (link
    papers' authors to people),
    ``trash`` (delete what is older than the trash days), ``integrity``
    (check stored contents), ``integrity-deep`` (also their SHA-256) or
    ``integrity-clean`` (check and remove unused stored contents), ``copy``
    (update the readable copy), ``copy-remove`` (delete it) or ``tidy``
    (retry stalled jobs, delete old jobs and expired logins)."""
    jobs = request.app.state.jobs
    sweeps = {
        "embeddings": queue_embedding_sweep,
        "text": queue_text_sweep,
        "ocr": queue_ocr_sweep,
        "published": queue_published_check,
        "references": queue_reference_lists,
        "errata": queue_errata_check,
        "authors": queue_author_linking,
        "trash": queue_empty_trash,
        "integrity": queue_integrity_check,
        "integrity-deep": lambda app: queue_integrity_check(app, deep=True),
        "integrity-clean": lambda app: queue_integrity_check(app, remove_unused=True),
        "copy": queue_readable_copy,
        "tidy": queue_tidy,
        "copy-remove": lambda app: queue_readable_copy(app, remove=True),
    }
    if job == "text-failed":
        count = reread_failed(db)
        queue_text_sweep(request.app.state.jobs)
        return {"queued": job, "files": count}
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


class Authentication(BaseModel):
    redirect_uri: str
    """To register at the identity provider."""
    secret_set: bool
    secret_from_environment: bool
    """Set with ``PAPERUS_OIDC_CLIENT_SECRET`` (then not changeable here)."""
    linked: int
    """Accounts that have logged in with the OIDC login."""
    sessions: int
    """Devices logged in now."""


@router.get("/authentication")
def authentication(request: Request, db: DB, admin: Admin) -> Authentication:
    """What the Authentication settings show besides the settings."""
    settings = request.app.state.settings
    config = system.load_config(db, settings)
    now = datetime.now(UTC)
    return Authentication(
        redirect_uri=public_base(request, config) + OIDC_CALLBACK,
        secret_set=system.oidc_secret(db, settings) is not None,
        secret_from_environment=bool(settings.oidc_client_secret),
        linked=db.scalar(select(func.count()).where(User.oidc_subject.is_not(None)))
        or 0,
        sessions=db.scalar(select(func.count()).where(LoginSession.expires_at > now))
        or 0,
    )


class Secret(BaseModel):
    secret: str | None = Field(None, max_length=1000)
    """None or empty: no secret (a public client)."""


@router.put("/authentication/secret", status_code=204)
def set_oidc_secret(body: Secret, db: DB, admin: Admin) -> None:
    """The OIDC login's client secret; never sent back."""
    system.save_oidc_secret(db, body.secret or None)
    db.commit()


class ProviderCheck(BaseModel):
    issuer: str = Field(max_length=500)


class ProviderFound(BaseModel):
    ok: bool
    error: str | None = None
    authorization_endpoint: str | None = None


@router.post("/authentication/check")
def check_provider(
    body: ProviderCheck, request: Request, admin: Admin
) -> ProviderFound:
    """Whether the identity provider answers at this address."""
    try:
        provider = oidc.discover(request.app.state.http, body.issuer, fresh=True)
    except oidc.LoginFailed as error:
        return ProviderFound(ok=False, error=str(error))
    return ProviderFound(
        ok=True, authorization_endpoint=provider.authorization_endpoint
    )


@router.delete("/sessions")
def end_all_sessions(request: Request, db: DB, admin: Admin) -> dict[str, int]:
    """Log everyone out on every device, except this one."""
    ended = auth.end_all_sessions(db, request_token(request) or "")
    db.commit()
    return {"ended": ended}


class ReadableCopy(BaseModel):
    path: str
    """The folder on the server (``PAPERUS_COPY_PATH``)."""
    free_bytes: int | None
    report: readable.CopyReport | None
    """The last update."""
    variables: dict[str, str]
    links_possible: bool
    """Hard links work only with files stored on a disk."""


@router.get("/readable-copy")
def readable_copy(request: Request, db: DB, admin: Admin) -> ReadableCopy:
    settings = request.app.state.settings
    root = settings.copy_path.resolve()
    return ReadableCopy(
        path=str(root),
        free_bytes=readable.free_space(root),
        report=readable.last_report(db),
        variables=readable.VARIABLES,
        links_possible=settings.storage_backend == "filesystem",
    )


class TemplateIn(BaseModel):
    template: str = Field(max_length=300)


class TemplatePreview(BaseModel):
    paths: list[str]
    """Where some of the library's files would go."""
    error: str | None = None


@router.post("/readable-copy/preview")
def preview_template(body: TemplateIn, db: DB, admin: Admin) -> TemplatePreview:
    try:
        template = readable.check_template(body.template)
    except readable.TemplateError as error:
        return TemplatePreview(paths=[], error=str(error))
    # From the administrator's own papers: being one reads no library.
    found = readable.wanted(
        db, template, limit=40, libraries=Access.of(db, admin).readable
    )
    return TemplatePreview(paths=[w.path for w in found[:8]])
