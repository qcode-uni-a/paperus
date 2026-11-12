import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from paperus_ml.encoder import Encoder, batches, pool
from tests.tiny_model import DIMENSIONS, TABLE, WORDS, write_tiny_model


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


def test_one_batch_at_a_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simultaneous requests take turns per batch instead of competing for
    the cores."""
    encoder = Encoder(write_tiny_model(tmp_path), tmp_path, max_batch_texts=1)
    running, most = 0, 0
    guard = threading.Lock()
    run = encoder.session.run

    def counting_run(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        nonlocal running, most
        with guard:
            running += 1
            most = max(most, running)
        time.sleep(0.01)
        try:
            return run(*args, **kwargs)
        finally:
            with guard:
                running -= 1

    monkeypatch.setattr(encoder.session, "run", counting_run)
    threads = [
        threading.Thread(target=encoder.embed, args=(["rain", "drought"], "passage"))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert most == 1


def test_models_taking_token_types(tmp_path: Path) -> None:
    plain = Encoder(write_tiny_model(tmp_path), tmp_path)
    vectors = plain.embed(["drought rivers", "rain"], "passage")
    with_types = Encoder(write_tiny_model(tmp_path, token_types=True), tmp_path)
    assert "token_type_ids" in with_types.input_names
    assert np.allclose(with_types.embed(["drought rivers", "rain"], "passage"), vectors)


def test_pool_last_and_output() -> None:
    hidden = np.array(
        [[[3.0, 4.0], [0.0, 2.0], [9.0, 9.0]], [[1.0, 0.0], [5.0, 5.0], [9.0, 9.0]]],
        dtype=np.float32,
    )
    mask = np.array([[1, 1, 0], [1, 0, 0]], dtype=np.int64)
    # Padding on the right: each text's last real token.
    assert np.allclose(pool(hidden, mask, "last"), [[0.0, 1.0], [1.0, 0.0]])
    # The model's own sentence vectors, normalized.
    own = np.array([[3.0, 4.0]], dtype=np.float32)
    assert np.allclose(pool(own, mask[:1], "output"), [[0.6, 0.8]])


def test_decoder_models(tmp_path: Path) -> None:
    """A decoder exported for generating text (Qwen3-Embedding): token
    positions and an empty past; its last token's vector."""
    spec = replace(write_tiny_model(tmp_path, decoder=True), pooling="last")
    encoder = Encoder(spec, tmp_path)
    assert {"position_ids", "past_key_values.0.key"} <= encoder.input_names
    vectors = encoder.embed(["drought rivers", "rain"], "passage")
    for row, word in enumerate(["rivers", "rain"]):
        expected = TABLE[WORDS.index(word)]
        assert np.allclose(vectors[row], expected / np.linalg.norm(expected))


def test_models_with_their_own_sentence_vectors(tmp_path: Path) -> None:
    """EmbeddingGemma: its pooling inside the model (``sentence_embedding``)."""
    spec = replace(write_tiny_model(tmp_path, sentence_output=True), pooling="output")
    own = Encoder(spec, tmp_path).embed(["drought rivers"], "passage")
    mean = Encoder(replace(spec, pooling="mean"), tmp_path).embed(
        ["drought rivers"], "passage"
    )
    assert np.allclose(own, mean)
