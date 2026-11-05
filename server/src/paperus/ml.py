"""Client for the machine learning service (paperus-ml).

Several addresses can be configured; the ones that answered last are tried
first and a failing one is skipped for a while (like Immich), so a GPU
machine can be added in front of a local fallback.
"""

import logging
import time
from typing import Any, Literal

import httpx2

from paperus.config import Settings

log = logging.getLogger(__name__)

Kind = Literal["query", "passage"]
RETRY_FAILED_AFTER = 30.0


class MLUnavailable(RuntimeError):
    pass


class MLClient:
    def __init__(
        self,
        urls: list[str],
        *,
        token: str | None = None,
        timeout: float = 120,
        http: httpx2.Client | None = None,
    ) -> None:
        self.urls = [url.rstrip("/") for url in urls]
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = http or httpx2.Client(timeout=timeout)
        self.http.headers.update(headers)
        self._failed_at: dict[str, float] = {}

    def _ordered_urls(self) -> list[str]:
        now = time.monotonic()
        healthy = [
            u
            for u in self.urls
            if now - self._failed_at.get(u, -1e9) > RETRY_FAILED_AFTER
        ]
        return healthy + [u for u in self.urls if u not in healthy]

    def embed(
        self, texts: list[str], *, model: str, kind: Kind, timeout: float | None = None
    ) -> list[list[float]]:
        """One vector per text; raises MLUnavailable if no service answers."""
        errors = []
        for url in self._ordered_urls():
            try:
                response = self.http.post(
                    f"{url}/embed",
                    json={"model": model, "kind": kind, "texts": texts},
                    timeout=timeout or httpx2.USE_CLIENT_DEFAULT,
                )
                response.raise_for_status()
            except httpx2.HTTPError as error:
                self._failed_at[url] = time.monotonic()
                errors.append(f"{url}: {error}")
                continue
            self._failed_at.pop(url, None)
            embeddings: list[list[float]] = response.json()["embeddings"]
            return embeddings
        raise MLUnavailable("; ".join(errors) or "no ML service configured")

    def status(self) -> list[tuple[str, str | None]]:
        """Each address with None if it answers, else the error."""
        result: list[tuple[str, str | None]] = []
        for url in self.urls:
            try:
                self.http.get(f"{url}/ping", timeout=5).raise_for_status()
                result.append((url, None))
            except httpx2.HTTPError as error:
                result.append((url, str(error) or type(error).__name__))
        return result

    def models(self) -> list[dict[str, Any]]:
        """The models the service offers (``GET /models``)."""
        return list(self._call("GET", "/models").json())

    def delete_model(self, name: str) -> None:
        """Remove a downloaded model from the service's cache."""
        self._call("DELETE", f"/models/{name}")

    def _call(self, method: str, path: str) -> httpx2.Response:
        errors = []
        for url in self._ordered_urls():
            try:
                response = self.http.request(method, f"{url}{path}", timeout=10)
                response.raise_for_status()
            except httpx2.HTTPError as error:
                errors.append(f"{url}: {error}")
                continue
            return response
        raise MLUnavailable("; ".join(errors) or "no ML service configured")

    def close(self) -> None:
        self.http.close()


def make_ml_client(settings: Settings) -> MLClient:
    return MLClient(
        settings.ml_urls, token=settings.ml_token, timeout=settings.ml_timeout
    )
