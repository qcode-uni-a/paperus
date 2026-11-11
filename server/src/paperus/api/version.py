"""What this server is, for the apps (docs/apps.md, "Versions"): the
website always matches its server, but an app's own parts (logging in in
the browser, notifications, offline use) talk to servers older and newer
than themselves."""

from fastapi import APIRouter
from pydantic import BaseModel

from paperus import __version__

router = APIRouter(tags=["health"])

OLDEST_APP = "0.0.20"
"""The oldest app this server serves fully: raised when a change would
break an app's own parts (then the website asks to update the app)."""

FEATURES = {"app_login": 1, "notifications": 1, "sync": 1}
"""What an app may use, each with its level: raised when it changes so an
older app would get it wrong (that app then goes without it); ``sync`` is
``/api/changes``, ``/api/web-files`` and the answers kept for offline use."""


class ServerVersion(BaseModel):
    version: str
    oldest_app: str
    """The oldest app this server serves fully."""
    features: dict[str, int]
    """What an app may use, with its level."""


@router.get("/api/version")
def server_version() -> ServerVersion:
    """This server's version and what it offers apps (no login needed)."""
    return ServerVersion(version=__version__, oldest_app=OLDEST_APP, features=FEATURES)
