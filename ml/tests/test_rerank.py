from pathlib import Path

import pytest

from paperus_ml.rerank import Reranker
from tests.tiny_model import tiny_rerank_score, write_tiny_reranker


def test_scores_keep_the_passages_order(tmp_path: Path) -> None:
    """Batched by length, padded, with the passage's tokens marked as such."""
    reranker = Reranker(write_tiny_reranker(tmp_path), tmp_path, max_batch_texts=2)
    passages = [
        "drought rivers rain",
        "cooking pasta",
        "rain",
        "unknown words here and there",
        "drought",
    ]
    scores = reranker.score("drought", passages)
    assert scores == pytest.approx([tiny_rerank_score("drought", p) for p in passages])
    assert max(range(len(passages)), key=scores.__getitem__) == 0


def test_long_passages_are_truncated(tmp_path: Path) -> None:
    reranker = Reranker(write_tiny_reranker(tmp_path, max_tokens=8), tmp_path)
    long = " ".join(["rain"] * 100)
    assert reranker.score("rain rivers", [long]) == pytest.approx(
        [tiny_rerank_score("rain rivers", long, max_tokens=8)]
    )


def test_smaller_batches_on_a_gpu(tmp_path: Path) -> None:
    """Asked for the GPU without one, ONNX Runtime runs it on the CPU."""
    spec = write_tiny_reranker(tmp_path)
    with pytest.warns(UserWarning, match="CUDAExecutionProvider"):
        reranker = Reranker(spec, tmp_path, max_batch_texts=64, device="cuda")
    assert reranker.max_batch_texts == 16
    assert reranker.device == "cpu"
    assert reranker.score("rain", ["rain"]) == [tiny_rerank_score("rain", "rain")]
