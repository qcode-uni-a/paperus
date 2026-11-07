"""Getting started: the first steps for a new person (and, for
administrators, for the server), each marked done once it is. The website
shows them on the library page until the person dismisses them."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import exists, func, select

from paperus import system
from paperus.api.admin import MLServiceState
from paperus.api.deps import DB, SessionUser
from paperus.ml import MLClient, MLRejected, MLUnavailable
from paperus.models import AccessToken, Import, Item, OAuthGrant, User

router = APIRouter(prefix="/api/me", tags=["auth"])

# The name the website gives the extension's token (settings/extension).
EXTENSION_TOKEN = "Browser extension"


class GPUStep(BaseModel):
    """Whether the machine learning service could use the machine's GPU."""

    done: bool
    advice: Literal[
        "in_use", "use_cuda_image", "pass_gpu", "update_driver", "install_driver"
    ]
    """in_use: it runs on the GPU; use_cuda_image: it is the CPU image, but
    the machine has a GPU it could use; pass_gpu: the GPU image, but the GPU
    is not passed to it (or not usable: ``problem``); update_driver /
    install_driver: the NVIDIA driver is too old, or none is loaded."""
    card: str
    """The GPU's name."""
    problem: str | None = None
    """Why the GPU image runs on the CPU, as the service says."""
    driver: int | None = None
    driver_needed: int


class ServerSteps(BaseModel):
    """What an administrator should set up before others rely on paperus."""

    backups: bool
    """Backups run on a schedule."""
    contact_email: bool
    """Metadata services (Crossref, Unpaywall) know whom to contact."""
    search: bool
    """The machine learning service answers (search by meaning, OCR)."""
    people: bool
    """Others can log in: more accounts, or OIDC login on."""
    gpu: GPUStep | None
    """Only where the machine has a suitable NVIDIA GPU (or uses one)."""
    ml_device: Literal["cpu", "cuda"] | None
    """Where the ML service runs its models; None if it does not answer."""


class GettingStarted(BaseModel):
    papers: bool
    """The person has added a paper."""
    imported: bool
    """They have imported a library from another reference manager."""
    extension: bool
    """They have connected the browser extension."""
    assistant: bool
    """They have connected an AI assistant (a token or a connected app)."""
    server: ServerSteps | None
    """For administrators only."""


@router.get("/getting-started")
def getting_started(request: Request, db: DB, user: SessionUser) -> GettingStarted:
    """Which of the first steps the person has taken."""
    tokens = select(AccessToken.name).where(
        AccessToken.user_id == user.id, AccessToken.grant_id.is_(None)
    )
    names = list(db.scalars(tokens))
    extension = any(name.startswith(EXTENSION_TOKEN) for name in names)
    assistant = any(not name.startswith(EXTENSION_TOKEN) for name in names) or bool(
        db.scalar(select(exists().where(OAuthGrant.user_id == user.id)))
    )
    return GettingStarted(
        papers=bool(db.scalar(select(exists().where(Item.added_by == user.id)))),
        imported=bool(db.scalar(select(exists().where(Import.user_id == user.id)))),
        extension=extension,
        assistant=assistant,
        server=_server_steps(request, db) if user.is_admin else None,
    )


def _server_steps(request: Request, db: DB) -> ServerSteps:
    config = system.load_config(db, request.app.state.settings)
    ml: MLClient = request.app.state.ml
    state = _ml_state(ml)
    people = (
        db.scalar(
            select(func.count()).select_from(User).where(User.deactivated_at.is_(None))
        )
        or 0
    )
    return ServerSteps(
        backups=system.load_backup_config(db).schedule != "off",
        contact_email=bool(config.contact_email),
        search=any(error is None for _, error in ml.status()),
        people=people > 1 or config.oidc_enabled,
        gpu=_gpu_step(state) if state else None,
        ml_device=("cuda" if state.device == "cuda" else "cpu") if state else None,
    )


def _ml_state(ml: MLClient) -> MLServiceState | None:
    try:
        return MLServiceState.model_validate(ml.service_config())
    except (MLUnavailable, MLRejected, ValueError):
        return None


def _gpu_step(state: MLServiceState) -> GPUStep | None:
    supported = [gpu.name for gpu in state.gpus if gpu.supported]
    if state.device == "cuda":
        names = supported or [gpu.name for gpu in state.gpus] or ["an NVIDIA GPU"]
        return GPUStep(
            done=True,
            advice="in_use",
            card=names[0],
            driver=state.driver,
            driver_needed=state.driver_needed,
        )
    if not supported:
        return None
    if state.driver is None:
        advice = "install_driver"
    elif state.driver < state.driver_needed:
        advice = "update_driver"
    elif state.cuda_image:
        advice = "pass_gpu"
    else:
        advice = "use_cuda_image"
    return GPUStep(
        done=False,
        advice=advice,
        card=supported[0],
        problem=state.gpu_problem if state.cuda_image else None,
        driver=state.driver,
        driver_needed=state.driver_needed,
    )
