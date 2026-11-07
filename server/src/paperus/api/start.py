"""Getting started: the first steps for a new person (and, for
administrators, for the server), each marked done once it is. The website
shows them on the library page until the person dismisses them."""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import exists, func, select

from paperus import system
from paperus.api.deps import DB, SessionUser
from paperus.ml import MLClient
from paperus.models import AccessToken, Import, Item, OAuthGrant, User

router = APIRouter(prefix="/api/me", tags=["auth"])

# The name the website gives the extension's token (settings/extension).
EXTENSION_TOKEN = "Browser extension"


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
    )
