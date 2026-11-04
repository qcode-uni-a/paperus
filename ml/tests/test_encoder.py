from pathlib import Path

import numpy as np

from paperus_ml.encoder import Encoder, batches, pool
from tests.tiny_model import DIMENSIONS, write_tiny_model


def test_pool_cls_and_mean() -> None:
    hidden = np.array([[[3.0, 4.0], [100.0, 0.0], [0.0, 0.0]]], dtype=np.float32)
    mask = np.array([[1, 1, 0]], dtype=np.int64)
    assert np.allclose(pool(hidden, mask, "cls"), [[0.6, 0.8]])
    mean = pool(hidden, mask, "mean")
    expected = np.array([51.5, 2.0]) / np.linalg.norm([51.5, 2.0])
    assert np.allclose(mean, [expected])


def test_batches_group_by_length() -> None:
    lengths = [10, 2, 9, 3, 100]
    assert batches(lengths, max_texts=2, max_tokens=1000) == [[1, 3], [2, 0], [4]]
    # The padded size (texts times longest) stays within the token budget.
    assert batches(lengths, max_texts=10, max_tokens=20) == [[1, 3], [2, 0], [4]]


def test_encoder(tmp_path: Path) -> None:
    spec = write_tiny_model(tmp_path)
    encoder = Encoder(spec, tmp_path, max_batch_texts=2)
    texts = ["drought rivers", "rain", "cooking pasta pasta", "drought rivers"]
    vectors = encoder.embed(texts, "passage")
    assert vectors.shape == (4, DIMENSIONS)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1)
    # Order is kept although batches are sorted by length.
    assert np.allclose(vectors[0], vectors[3])
    assert not np.allclose(vectors[0], vectors[2])
    # Same text, other prefix: another vector.
    query = encoder.embed(["drought rivers"], "query")
    assert not np.allclose(query[0], vectors[0])


def test_long_texts_are_truncated(tmp_path: Path) -> None:
    spec = write_tiny_model(tmp_path)
    encoder = Encoder(spec, tmp_path)
    long = " ".join(["rain"] * 1000)
    assert encoder.embed([long], "passage").shape == (1, DIMENSIONS)
