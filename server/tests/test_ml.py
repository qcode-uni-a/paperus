"""The client for the ML service: several addresses, failures, retries and
timeouts (without a database)."""

from collections.abc import Callable

import httpx2
import pytest
from prometheus_client import REGISTRY

from paperus.config import Settings
from paperus.ml import (
    MLClient,
    MLLoading,
    MLRejected,
    MLUnavailable,
    make_ml_client,
)
from tests.conftest import FakeML

Handler = Callable[[httpx2.Request], httpx2.Response]
PNG = b"\x89PNG scan"


def routed(routes: dict[str, Handler], seen: list[httpx2.Request]) -> httpx2.Client:
    """Requests to each host go to its handler; the hosts not listed are down."""

    def route(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        handler = routes.get(request.url.host)
        if handler is None:
            raise httpx2.ConnectError(f"{request.url.host} down")
        return handler(request)

    return httpx2.Client(transport=httpx2.MockTransport(route))


def answer(status: int, *, json: object = None, text: str | None = None) -> Handler:
    return lambda request: httpx2.Response(status, json=json, text=text)


def calls(operation: str, outcome: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "paperus_ml_calls_total", {"operation": operation, "outcome": outcome}
        )
        or 0.0
    )


def test_settings_make_the_client() -> None:
    client = make_ml_client(
        Settings(ml_urls=["http://gpu/", "http://local"], ml_token="t", ml_timeout=7)
    )
    assert client.urls == ["http://gpu", "http://local"]
    assert client.http.headers["Authorization"] == "Bearer t"
    assert client.http.timeout.read == 7
    client.close()
    assert client.http.is_closed
    assert "Authorization" not in make_ml_client(Settings(ml_token=None)).http.headers


def test_timeouts(fake_ml: FakeML) -> None:
    seen: list[httpx2.Request] = []
    client = MLClient(["http://ml"], http=routed({"ml": fake_ml}, seen))
    client.embed(["rain"], model="bge-m3", kind="query")
    client.embed(["rain"], model="bge-m3", kind="query", timeout=3)
    client.rerank("rain", ["drizzle"], model="bge-reranker-v2-m3", timeout=4)
    client.ocr(PNG, model="pp-ocrv6-small")
    default, given, rerank, ocr = (r.extensions["timeout"]["read"] for r in seen)
    assert default == client.http.timeout.read
    assert (given, rerank, ocr) == (3, 4, 300)


def test_status_says_why(fake_ml: FakeML) -> None:
    client = MLClient(
        ["http://ml", "http://broken", "http://gone"],
        http=routed({"ml": fake_ml, "broken": answer(500)}, []),
    )
    up, broken, gone = client.status()
    assert up == ("http://ml", None)
    assert broken[0] == "http://broken" and "500" in str(broken[1])
    assert gone == ("http://gone", "gone down")

    def silent(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("")

    client = MLClient(["http://ml"], http=routed({"ml": silent}, []))
    assert client.status() == [("http://ml", "ReadTimeout")]


def test_rerank_and_ocr_fall_back_and_skip_failing(fake_ml: FakeML) -> None:
    seen: list[httpx2.Request] = []
    client = MLClient(
        ["http://gpu", "http://broken", "http://ml"],
        http=routed({"broken": answer(500, text="out of memory"), "ml": fake_ml}, seen),
    )
    ok = calls("rerank", "ok")
    scores = client.rerank(
        "rain", ["dry", "drizzle"], model="bge-reranker-v2-m3", timeout=5
    )
    assert scores == [0.0, 1.0]
    assert calls("rerank", "ok") == ok + 1
    assert [r.url.host for r in seen] == ["gpu", "broken", "ml"]
    # Both failing addresses are tried last for a while.
    seen.clear()
    read = client.ocr(PNG, model="pp-ocrv6-small")
    assert read.text.startswith(FakeML.SCANNED)
    assert (read.width, read.height) == (1700, 2200)
    assert seen[0].headers["Content-Type"] == "application/octet-stream"
    assert [r.url.host for r in seen] == ["ml"]


@pytest.mark.parametrize("operation", ["embed", "rerank", "ocr"])
def test_loading_rejected_and_down(operation: str) -> None:
    def ask(client: MLClient) -> object:
        if operation == "embed":
            return client.embed(["x"], model="m", kind="query")
        if operation == "rerank":
            return client.rerank("q", ["p"], model="m", timeout=5)
        return client.ocr(PNG, model="m")

    # One address loading, another down: try again later.
    loading = answer(503, json={"detail": "model 'm' is loading"})
    client = MLClient(["http://ml", "http://gone"], http=routed({"ml": loading}, []))
    before = calls(operation, "loading")
    with pytest.raises(MLLoading, match=r"is loading.*gone down"):
        ask(client)
    assert calls(operation, "loading") == before + 1
    # A loading service is not broken; one that is down is.
    assert list(client._failed_at) == ["http://gone"]

    # Refused: no other address is asked.
    seen: list[httpx2.Request] = []
    client = MLClient(
        ["http://ml", "http://other"],
        http=routed({"ml": answer(422, text="not JSON")}, seen),
    )
    before = calls(operation, "rejected")
    with pytest.raises(MLRejected) as refused:
        ask(client)
    assert (refused.value.status, refused.value.detail) == (422, "not JSON")
    assert len(seen) == 1
    assert calls(operation, "rejected") == before + 1

    before = calls(operation, "unavailable")
    with pytest.raises(MLUnavailable, match="no ML service configured"):
        ask(MLClient([], http=routed({}, [])))
    assert calls(operation, "unavailable") == before + 1


def test_device_and_vectors_are_asked_once_a_minute(fake_ml: FakeML) -> None:
    seen: list[httpx2.Request] = []
    client = MLClient(["http://ml"], http=routed({"ml": fake_ml}, seen))
    fake_ml.device = "cuda"
    fake_ml.variant = "fp16"
    assert client.device() == "cuda"
    assert client.vectors_name("bge-m3") == "bge-m3@fp16"
    fake_ml.device = "cpu"
    fake_ml.variant = None
    assert client.device() == "cuda"
    assert client.vectors_name("bge-m3") == "bge-m3@fp16"
    assert [r.url.path for r in seen] == ["/config", "/models"]
    with pytest.raises(MLRejected, match="no model 'gpt-9'"):
        client.vectors_name("gpt-9")

    # A service that does not say runs on the CPU.
    no_device = answer(200, json={"threads": 0})
    assert MLClient(["http://ml"], http=routed({"ml": no_device}, [])).device() == "cpu"


def test_models_config_and_settings(fake_ml: FakeML) -> None:
    client = MLClient(["http://gone", "http://ml"], http=routed({"ml": fake_ml}, []))
    assert "bge-m3" in [m["name"] for m in client.models()]
    client.delete_model("bge-m3")
    assert fake_ml.deleted == ["bge-m3"]
    config = client.service_config()
    assert config["url"] == "http://ml"
    assert config["cores"] == 8
    # Every address is sent the settings; the ones that fail say so.
    errors = client.configure(threads=4, keep=["bge-m3"])
    assert fake_ml.config == {"threads": 4, "keep": ["bge-m3"]}
    assert len(errors) == 1 and errors[0].startswith("http://gone: ")


def test_calls_fall_back_or_fail(fake_ml: FakeML) -> None:
    seen: list[httpx2.Request] = []
    client = MLClient(
        ["http://broken", "http://ml"],
        http=routed({"broken": answer(502), "ml": fake_ml}, seen),
    )
    assert client.models()
    assert [r.url.host for r in seen] == ["broken", "ml"]

    refusing = answer(404, json={"detail": "no such model"})
    client = MLClient(["http://ml"], http=routed({"ml": refusing}, []))
    with pytest.raises(MLRejected, match="404: no such model"):
        client.delete_model("x")

    client = MLClient(["http://a", "http://b"], http=routed({"b": answer(500)}, []))
    with pytest.raises(MLUnavailable, match=r"http://a: a down; http://b: 500"):
        client.models()


def test_speed_is_measured_once(fake_ml: FakeML) -> None:
    seen: list[httpx2.Request] = []
    client = MLClient(["http://gone", "http://ml"], http=routed({"ml": fake_ml}, seen))
    speed = client.measure_speed("bge-m3")
    assert speed["passages_per_second"] == 8.0
    assert speed["url"] == "http://ml"
    assert [r.url.host for r in seen] == ["gone", "ml"]
    assert seen[-1].extensions["timeout"]["read"] == 300
    # The unreachable address is tried last now.
    with pytest.raises(MLRejected) as refused:
        client.measure_speed("gpt-9")
    assert refused.value.status == 404
    assert seen[-1].url.host == "ml"

    # A model still loading is not measured on another service.
    loading = answer(503, json={"detail": "downloading"})
    client = MLClient(
        ["http://ml", "http://other"],
        http=routed({"ml": loading, "other": fake_ml}, []),
    )
    with pytest.raises(MLLoading, match="downloading"):
        client.measure_speed("bge-m3")

    with pytest.raises(MLUnavailable, match="no ML service answers"):
        MLClient(["http://gone"], http=routed({}, [])).measure_speed("bge-m3")
