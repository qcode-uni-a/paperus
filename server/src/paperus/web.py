"""Serving the built website (``web/``, a static single-page app)."""

import hashlib
from functools import cache
from pathlib import Path
from typing import Any

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

    @cache
    def files() -> dict[str, Any]:
        found = [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
            for path in sorted(root.rglob("*"))
            if path.is_file()
        ]
        return {"fallback": FALLBACK, "files": found}

    @app.get("/api/web-files", include_in_schema=False)
    def web_files() -> dict[str, Any]:
        """The website's files with their SHA-256: the app keeps a copy of
        the version it last loaded, to run it offline (docs/apps.md)."""
        return files()

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
