"""Running a reranker (cross-encoder) with ONNX Runtime: it reads a query
and a passage together and says how well they fit, more exactly than
comparing their vectors; used to reorder the best few dozen search hits."""

import threading
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from paperus_ml import metrics
from paperus_ml.device import Device, run_options
from paperus_ml.encoder import batches, model_inputs, open_session, open_tokenizer
from paperus_ml.models import ModelSpec


class Reranker:
    def __init__(
        self,
        spec: ModelSpec,
        model_dir: Path,
        *,
        intra_op_threads: int = 0,
        max_batch_texts: int = 32,
        max_batch_tokens: int = 16384,
        device: Device = "cpu",
    ) -> None:
        self.spec = spec
        # Smaller batches on a GPU: a query with 16 long passages already
        # keeps it busy, and needs half the memory of 32.
        self.max_batch_texts = (
            min(max_batch_texts, 16) if device == "cuda" else max_batch_texts
        )
        self.max_batch_tokens = max_batch_tokens
        self.tokenizer = open_tokenizer(
            model_dir / spec.tokenizer_file, spec.max_tokens
        )
        self.session, self.device = open_session(
            model_dir / spec.onnx_file_for(device), intra_op_threads, device
        )
        self.input_names = {i.name for i in self.session.get_inputs()}
        self.run_options = run_options(self.device)
        # One batch at a time, as for embedding models (see Encoder).
        self.running = threading.RLock()

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """How well each passage answers the query (higher is better; only
        the order means something)."""
        encodings = self.tokenizer.encode_batch([(query, p) for p in passages])
        result = [0.0] * len(passages)
        groups = batches(
            [len(e.ids) for e in encodings], self.max_batch_texts, self.max_batch_tokens
        )
        for group in groups:
            feed = model_inputs([encodings[i] for i in group], self.input_names)
            with self.running:
                started = time.perf_counter()
                logits = self.session.run(None, feed, self.run_options)[0]
                metrics.BATCH_SECONDS.labels(self.spec.name).observe(
                    time.perf_counter() - started
                )
            values = np.asarray(logits, dtype=np.float32).reshape(len(group), -1)[:, 0]
            for row, index in enumerate(group):
                result[index] = float(values[row])
        return result
