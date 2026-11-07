"""Serving the built website (``web/``, a static single-page app)."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# The SPA's entry page for every route that is not a file.
FALLBACK = "200.html"
# Pages are never shown inside another site's frame (where a hidden page
# could be clicked, e.g. "Allow" when connecting an app).
NO_FRAMING = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


def mount_web(app: FastAPI, root: Path) -> None:
    """Serve ``root``; unknown paths outside ``/api`` get the app's entry page."""
    root = root.resolve()
    app.mount("/_app", StaticFiles(directory=root / "_app"), name="web-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "not found")
        file = (root / path).resolve()
        if path and file.is_relative_to(root) and file.is_file():
            page = file.suffix == ".html"
            return FileResponse(file, headers=NO_FRAMING if page else None)
        return FileResponse(
            root / FALLBACK, headers={"Cache-Control": "no-cache", **NO_FRAMING}
        )
