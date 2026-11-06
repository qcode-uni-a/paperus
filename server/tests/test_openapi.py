"""The API description the website, the TypeScript client and the browser
extension are typed with (``web/src/lib/api/openapi.json``) matches the API."""

import json
from pathlib import Path

from paperus.app import create_app
from paperus.config import Settings

SCHEMA = Path(__file__).parents[2] / "web" / "src" / "lib" / "api" / "openapi.json"


def test_committed_schema_is_current(settings: Settings) -> None:
    committed = json.loads(SCHEMA.read_text())
    assert committed == create_app(settings).openapi(), (
        "The API changed: run `npm run api` in web/ and commit the result "
        "(then check the extension: `npm run check` in extension/)."
    )
