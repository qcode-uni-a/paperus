"""Details for a DOI from doi.org: answers good and bad."""

import httpx2
import pytest

from paperus.config import Settings
from paperus.metadata import (
    DOINotFound,
    MetadataUnavailable,
    csl_title,
    csl_type,
    fetch_csl,
    lookup_doi,
    make_http_client,
    version_kind,
)
from paperus.models import VersionKind


def client_answering(response: httpx2.Response) -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(lambda request: response))


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx2.Response(404), DOINotFound),
        (httpx2.Response(503), MetadataUnavailable),
        (httpx2.Response(200, text="<html>"), MetadataUnavailable),
        (httpx2.Response(200, json=["not", "an", "object"]), MetadataUnavailable),
    ],
)
def test_bad_answers(response: httpx2.Response, error: type[Exception]) -> None:
    with pytest.raises(error):
        fetch_csl(client_answering(response), "10.1234/x")


def test_titles_in_lists_and_preprints() -> None:
    m = 'xmlns:mml="http://www.w3.org/1998/Math/MathML"'
    csl = {
        "type": "posted-content",
        "title": [f"The <mml:math {m}><mml:mi>g</mml:mi></mml:math> factor", 3],
    }
    found, kind = lookup_doi(
        client_answering(httpx2.Response(200, json=csl)), "10.1234/x"
    )
    assert found == {"type": "article", "title": ["The $g$ factor", 3]}
    assert kind == VersionKind.PREPRINT
    assert csl_title(found) == "The $g$ factor"
    assert csl_title({"title": []}) == "(untitled)"
    assert csl_type({"type": "journal-article"}) == "article-journal"
    assert version_kind("10.1234/x", {"type": "journal-article"}) == (
        VersionKind.PUBLISHED
    )


def test_http_client_names_itself() -> None:
    settings = Settings(contact_email="library@example.org")
    with make_http_client(settings) as client:
        assert "mailto:library@example.org" in client.headers["User-Agent"]


def test_unreachable_and_arxiv() -> None:
    def offline(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("offline")

    with pytest.raises(MetadataUnavailable, match="offline"):
        fetch_csl(httpx2.Client(transport=httpx2.MockTransport(offline)), "10.1/x")
    csl, kind = lookup_doi(
        client_answering(
            httpx2.Response(200, json={"type": "article-journal", "title": " A  b "})
        ),
        "10.48550/arxiv.2101.00001",
    )
    assert (csl, kind) == ({"type": "article", "title": "A b"}, VersionKind.PREPRINT)
