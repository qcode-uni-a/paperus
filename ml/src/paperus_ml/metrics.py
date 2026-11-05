"""Prometheus metrics of the ML service, on a port of their own
(``PAPERUS_ML_METRICS_PORT``): requests, batch times, loaded models."""

from collections.abc import Callable, Iterator

from prometheus_client import REGISTRY, Counter, Histogram, start_http_server
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

REQUESTS = Counter(
    "paperus_ml_requests_total",
    "Embedding requests, by model, kind and outcome",
    ["model", "kind", "outcome"],
)
TEXTS = Counter("paperus_ml_texts_total", "Texts embedded", ["model", "kind"])
BATCH_SECONDS = Histogram(
    "paperus_ml_batch_duration_seconds",
    "Time to run one batch through a model",
    ["model"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)


class ModelsCollector(Collector):
    """Loaded and loading models, read at each scrape."""

    def __init__(
        self, loaded: Callable[[], list[str]], loading: Callable[[], list[str]]
    ) -> None:
        self.loaded = loaded
        self.loading = loading

    def collect(self) -> Iterator[Metric]:
        gauge = GaugeMetricFamily(
            "paperus_ml_model_loaded",
            "1 for each model in memory, 0.5 while loading",
            labels=["model"],
        )
        for name in self.loaded():
            gauge.add_metric([name], 1.0)
        for name in self.loading():
            gauge.add_metric([name], 0.5)
        yield gauge


_started = False


def serve(port: int, collector: Collector) -> None:
    global _started
    if _started:
        return
    REGISTRY.register(collector)
    start_http_server(port)
    _started = True
