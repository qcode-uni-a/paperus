"""Client for the machine learning service (paperus-ml).

Several addresses can be configured; the ones that answered last are tried
first and a failing one is skipped for a while, so a GPU
machine can be added in front of a local fallback.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx2

from paperus import metrics
from paperus.config import Settings

log = logging.getLogger(__name__)

Kind = Literal["query", "passage"]
RETRY_FAILED_AFTER = 30.0
# How long the service's answer to "what are this model's vectors stored
# as" is reused (it changes only when the service restarts on other hardware).
VECTORS_TTL = 60.0


@dataclass
class Embedded:
    vectors: str
    """What to store them as: the model's name, or with the variant of the
    service's model file (``…@fp16``)."""
    values: list[list[float]]


class MLUnavailable(RuntimeError):
    pass


class MLLoading(MLUnavailable):
    """The service is downloading or loading the model; ask again later."""


class MLRejected(RuntimeError):
    """The service refused the request (e.g. an unknown model): trying
    again or another address would not help."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def _detail(response: httpx2.Response) -> str:
    try:
        return str(response.json().get("detail") or response.text)
    except ValueError:
        return response.text


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
        self._vectors: dict[str, tuple[str, float]] = {}
        self._device: tuple[str, float] | None = None

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
        return self.embed_named(texts, model=model, kind=kind, timeout=timeout).values

    def embed_named(
        self, texts: list[str], *, model: str, kind: Kind, timeout: float | None = None
    ) -> Embedded:
        """One vector per text, and what to store them as (see
        ``vectors_name``)."""
        started = time.perf_counter()
        try:
            vectors = self._embed(texts, model=model, kind=kind, timeout=timeout)
        except MLLoading:
            metrics.ML_CALLS.labels("embed", "loading").inc()
            raise
        except MLRejected:
            metrics.ML_CALLS.labels("embed", "rejected").inc()
            raise
        except MLUnavailable:
            metrics.ML_CALLS.labels("embed", "unavailable").inc()
            raise
        metrics.ML_CALLS.labels("embed", "ok").inc()
        metrics.ML_SECONDS.labels("embed").observe(time.perf_counter() - started)
        return vectors

    def _embed(
        self, texts: list[str], *, model: str, kind: Kind, timeout: float | None
    ) -> Embedded:
        errors = []
        loading = False
        for url in self._ordered_urls():
            try:
                response = self.http.post(
                    f"{url}/embed",
                    json={"model": model, "kind": kind, "texts": texts},
                    timeout=timeout or httpx2.USE_CLIENT_DEFAULT,
                )
            except httpx2.HTTPError as error:
                self._failed_at[url] = time.monotonic()
                errors.append(f"{url}: {error}")
                continue
            if response.status_code == 503:  # loading the model: not broken
                loading = True
                errors.append(f"{url}: {_detail(response)}")
                continue
            if 400 <= response.status_code < 500:
                raise MLRejected(response.status_code, _detail(response))
            if response.is_error:
                self._failed_at[url] = time.monotonic()
                errors.append(f"{url}: {response.status_code} {_detail(response)}")
                continue
            self._failed_at.pop(url, None)
            body = response.json()
            # Services before 0.0.11 do not say: their vectors are the model's.
            return Embedded(body.get("vectors") or model, body["embeddings"])
        message = "; ".join(errors) or "no ML service configured"
        raise MLLoading(message) if loading else MLUnavailable(message)

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

    def rerank(
        self, query: str, passages: list[str], *, model: str, timeout: float
    ) -> list[float]:
        """How well each passage answers the query (higher fits better), from
        the first service that answers; raises MLUnavailable, MLLoading or
        MLRejected."""
        errors = []
        loading = False
        for url in self._ordered_urls():
            try:
                response = self.http.post(
                    f"{url}/rerank",
                    json={"model": model, "query": query, "passages": passages},
                    timeout=timeout,
                )
            except httpx2.HTTPError as error:
                self._failed_at[url] = time.monotonic()
                errors.append(f"{url}: {error}")
                continue
            if response.status_code == 503:
                loading = True
                errors.append(f"{url}: {_detail(response)}")
                continue
            if 400 <= response.status_code < 500:
                metrics.ML_CALLS.labels("rerank", "rejected").inc()
                raise MLRejected(response.status_code, _detail(response))
            if response.is_error:
                errors.append(f"{url}: {response.status_code} {_detail(response)}")
                continue
            metrics.ML_CALLS.labels("rerank", "ok").inc()
            scores: list[float] = response.json()["scores"]
            return scores
        metrics.ML_CALLS.labels("rerank", "loading" if loading else "unavailable").inc()
        message = "; ".join(errors) or "no ML service configured"
        raise MLLoading(message) if loading else MLUnavailable(message)

    def device(self) -> str:
        """Where the first ML service runs its models ("cpu" or "cuda"),
        asked at most once a minute; "cpu" if it does not say."""
        if self._device and time.monotonic() - self._device[1] < VECTORS_TTL:
            return self._device[0]
        device = str(self.service_config().get("device") or "cpu")
        self._device = (device, time.monotonic())
        return device

    def vectors_name(self, model: str) -> str:
        """What the model's vectors are stored as: its name, or with the
        variant of the file the service runs (``…@fp16`` on a GPU), as
        vectors of different files must not be mixed. Raises MLUnavailable."""
        cached = self._vectors.get(model)
        if cached and time.monotonic() - cached[1] < VECTORS_TTL:
            return cached[0]
        for entry in self.models():
            if entry.get("name") == model:
                name = str(entry.get("vectors") or model)
                self._vectors[model] = (name, time.monotonic())
                return name
        raise MLRejected(404, f"the ML service has no model {model!r}")

    def models(self) -> list[dict[str, Any]]:
        """The models the service offers (``GET /models``)."""
        return list(self._call("GET", "/models").json())

    def delete_model(self, name: str) -> None:
        """Remove a downloaded model from the service's cache."""
        self._call("DELETE", f"/models/{name}")

    def service_config(self) -> dict[str, Any]:
        """Threads, kept models and usable cores of the first service that
        answers, with its address as ``url``."""
        response = self._call("GET", "/config")
        return {**response.json(), "url": str(response.url).removesuffix("/config")}

    def configure(self, *, threads: int | None, keep: list[str]) -> list[str]:
        """Send the administration's settings to every service; returns the
        errors of those that did not take them."""
        errors = []
        for url in self.urls:
            try:
                self.http.put(
                    f"{url}/config",
                    json={"threads": threads, "keep": keep},
                    timeout=10,
                ).raise_for_status()
            except httpx2.HTTPError as error:
                errors.append(f"{url}: {error}")
        return errors

    def measure_speed(self, name: str) -> dict[str, Any]:
        """Time the model on sample passages, on the first service that
        answers (not again on the next one: a measurement can take a
        minute). Raises MLLoading while the model downloads or loads."""
        for url in self._ordered_urls():
            try:
                response = self.http.post(f"{url}/models/{name}/speed", timeout=300)
            except httpx2.HTTPError as error:
                self._failed_at[url] = time.monotonic()
                log.info("speed test: %s unreachable: %s", url, error)
                continue
            if response.status_code == 503:
                raise MLLoading(_detail(response))
            if response.is_error:
                raise MLRejected(response.status_code, _detail(response))
            return {**response.json(), "url": url}
        raise MLUnavailable("no ML service answers")

    def _call(self, method: str, path: str, timeout: float = 10) -> httpx2.Response:
        errors = []
        for url in self._ordered_urls():
            try:
                response = self.http.request(method, f"{url}{path}", timeout=timeout)
            except httpx2.HTTPError as error:
                errors.append(f"{url}: {error}")
                continue
            if 400 <= response.status_code < 500:
                raise MLRejected(response.status_code, _detail(response))
            if response.is_error:
                errors.append(f"{url}: {response.status_code}")
                continue
            return response
        raise MLUnavailable("; ".join(errors) or "no ML service configured")

    def close(self) -> None:
        self.http.close()


def make_ml_client(settings: Settings) -> MLClient:
    return MLClient(
        settings.ml_urls, token=settings.ml_token, timeout=settings.ml_timeout
    )
