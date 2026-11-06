"""Downloads real models (multilingual-e5-small, 118 MB, and smaller ones):
PAPERUS_ML_TEST_DOWNLOAD=1."""

import os
from pathlib import Path

import pytest

from paperus_ml.config import Settings
from paperus_ml.encoder import Encoder
from paperus_ml.manager import ModelManager
from paperus_ml.ocr import Reader
from paperus_ml.rerank import Reranker
from paperus_ml.samples import sample_page

pytestmark = [
    pytest.mark.download,
    pytest.mark.skipif(
        not os.environ.get("PAPERUS_ML_TEST_DOWNLOAD"), reason="downloads a model"
    ),
]


def test_meaning_across_languages(tmp_path: Path) -> None:
    cache = Path(os.environ.get("PAPERUS_ML_CACHE_PATH", tmp_path))
    encoder = ModelManager(Settings(cache_path=cache)).get("multilingual-e5-small")
    assert isinstance(encoder, Encoder)
    passages = encoder.embed(
        [
            "Gaps shorter than five days were filled by linear interpolation.",
            "Wir haben den SPEI auf einer Skala von drei Monaten berechnet.",
            "Boil the pasta for nine minutes in salted water.",
        ],
        "passage",
    )
    query = encoder.embed(["how did they handle missing data?"], "query")[0]
    scores = passages @ query
    assert scores.argmax() == 0
    drought = encoder.embed(["drought index"], "query")[0]
    assert (passages @ drought).argmax() == 1


def test_reranker_puts_the_answer_first(tmp_path: Path) -> None:
    """Downloads ms-marco-MiniLM-L-6-v2 (23 MB)."""
    cache = Path(os.environ.get("PAPERUS_ML_CACHE_PATH", tmp_path))
    reranker = ModelManager(Settings(cache_path=cache)).get("ms-marco-minilm-l6")
    assert isinstance(reranker, Reranker)
    scores = reranker.score(
        "how were missing days filled?",
        [
            "Boil the pasta for nine minutes in salted water.",
            "Gaps shorter than five days were filled by linear interpolation.",
            "Rain gauges were checked weekly.",
        ],
    )
    assert max(range(3), key=scores.__getitem__) == 1


def test_ocr_reads_a_two_column_page(tmp_path: Path) -> None:
    """Downloads PP-OCRv6 small (31 MB)."""
    cache = Path(os.environ.get("PAPERUS_ML_CACHE_PATH", tmp_path))
    reader = ModelManager(Settings(cache_path=cache)).get("pp-ocrv6-small")
    assert isinstance(reader, Reader)
    page = reader.read(sample_page())
    assert (page.width, page.height) == (1654, 2339)
    assert "blind zones below the radar beam" in " ".join(page.text.split())
    # The left column first, then the right one (not line by line across).
    in_right = [line.box[0] > 800 for line in page.lines]
    assert in_right == sorted(in_right) and 30 < in_right.count(False) < 60
