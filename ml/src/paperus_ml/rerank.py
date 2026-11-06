"""Running a reranker (cross-encoder) with ONNX Runtime: it reads a query
and a passage together and says how well they fit, more exactly than
comparing their vectors; used to reorder the best few dozen search hits."""

import threading
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import onnxruntime
from tokenizers import Tokenizer

from paperus_ml import metrics
from paperus_ml.device import CUDA, Device, providers, run_options
from paperus_ml.encoder import batches, session_options
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
        self.tokenizer = Tokenizer.from_file(str(model_dir / spec.tokenizer_file))
        self.tokenizer.enable_truncation(spec.max_tokens)
        self.tokenizer.no_padding()
        self.session = onnxruntime.InferenceSession(
            str(model_dir / spec.onnx_file_for(device)),
            sess_options=session_options(intra_op_threads),
            providers=providers(device),
        )
        self.device: Device = (
            "cuda" if self.session.get_providers()[0] == CUDA else "cpu"
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
            width = max(len(encodings[i].ids) for i in group)
            ids = np.zeros((len(group), width), dtype=np.int64)
            mask = np.zeros_like(ids)
            types = np.zeros_like(ids)
            for row, index in enumerate(group):
                encoding = encodings[index]
                ids[row, : len(encoding.ids)] = encoding.ids
                mask[row, : len(encoding.ids)] = 1
                types[row, : len(encoding.ids)] = encoding.type_ids
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.input_names:
                feed["token_type_ids"] = types
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
