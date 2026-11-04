"""Downloads multilingual-e5-small (118 MB): PAPERUS_ML_TEST_DOWNLOAD=1."""

import os
from pathlib import Path

import pytest

from paperus_ml.config import Settings
from paperus_ml.manager import ModelManager

pytestmark = [
    pytest.mark.download,
    pytest.mark.skipif(
        not os.environ.get("PAPERUS_ML_TEST_DOWNLOAD"), reason="downloads a model"
    ),
]


def test_meaning_across_languages(tmp_path: Path) -> None:
    cache = Path(os.environ.get("PAPERUS_ML_CACHE_PATH", tmp_path))
    encoder = ModelManager(Settings(cache_path=cache)).get("multilingual-e5-small")
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
