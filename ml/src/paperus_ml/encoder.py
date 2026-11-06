"""Running an embedding model with ONNX Runtime."""

import threading
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt
import onnxruntime
from tokenizers import Encoding, Tokenizer

from paperus_ml import metrics
from paperus_ml.device import CUDA, Device, providers
from paperus_ml.models import Kind, ModelSpec

Vectors = npt.NDArray[np.float32]


def session_options(intra_op_threads: int) -> onnxruntime.SessionOptions:
    options = onnxruntime.SessionOptions()
    options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
    # One graph at a time, parallel inside operators.
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = intra_op_threads
    # Denormal floats are slow on CPUs and irrelevant for embeddings.
    options.add_session_config_entry("session.set_denormal_as_zero", "1")
    return options


def pool(
    hidden: npt.NDArray[np.float32],
    mask: npt.NDArray[np.int64],
    how: str,
) -> Vectors:
    """Sentence vectors from token vectors, L2-normalized."""
    if how == "cls":
        vectors = hidden[:, 0]
    else:
        weights = mask[..., None].astype(np.float32)
        vectors = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-12)).astype(np.float32)


def batches(lengths: Sequence[int], max_texts: int, max_tokens: int) -> list[list[int]]:
    """Group text indices by length, so little padding is computed."""
    order = sorted(range(len(lengths)), key=lambda i: lengths[i])
    groups: list[list[int]] = []
    current: list[int] = []
    for index in order:
        padded = (len(current) + 1) * lengths[index]
        if current and (len(current) >= max_texts or padded > max_tokens):
            groups.append(current)
            current = []
        current.append(index)
    if current:
        groups.append(current)
    return groups


class Encoder:
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
        self.max_batch_texts = max_batch_texts
        self.max_batch_tokens = max_batch_tokens
        self.tokenizer = Tokenizer.from_file(str(model_dir / spec.tokenizer_file))
        self.tokenizer.enable_truncation(spec.max_tokens)
        self.tokenizer.no_padding()
        self.session = onnxruntime.InferenceSession(
            str(model_dir / spec.onnx_file_for(device)),
            sess_options=session_options(intra_op_threads),
            providers=providers(device),
        )
        # Where it actually runs: ONNX Runtime falls back to the CPU when
        # the GPU cannot be used.
        self.device: Device = (
            "cuda" if self.session.get_providers()[0] == CUDA else "cpu"
        )
        self.input_names = {i.name for i in self.session.get_inputs()}
        # One batch at a time: each already uses all cores, so batches of
        # simultaneous requests would only compete for them. Per batch, not
        # per request, so a search query waits for one batch at most.
        # Reentrant: the speed test holds it across all its batches.
        self.running = threading.RLock()

    def embed(self, texts: Sequence[str], kind: Kind) -> Vectors:
        prefix = self.spec.prefix(kind)
        encodings = self.tokenizer.encode_batch([prefix + t for t in texts])
        result = np.zeros((len(texts), self.spec.dimensions), dtype=np.float32)
        groups = batches(
            [len(e.ids) for e in encodings], self.max_batch_texts, self.max_batch_tokens
        )
        for group in groups:
            result[group] = self._run([encodings[i] for i in group])
        return result

    def _run(self, encodings: list[Encoding]) -> Vectors:
        width = max(len(e.ids) for e in encodings)
        ids = np.zeros((len(encodings), width), dtype=np.int64)
        mask = np.zeros((len(encodings), width), dtype=np.int64)
        for row, encoding in enumerate(encodings):
            ids[row, : len(encoding.ids)] = encoding.ids
            mask[row, : len(encoding.ids)] = 1
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.zeros_like(ids)
        with self.running:
            started = time.perf_counter()
            hidden = self.session.run(None, feed)[0]
            metrics.BATCH_SECONDS.labels(self.spec.name).observe(
                time.perf_counter() - started
            )
        return pool(np.asarray(hidden, dtype=np.float32), mask, self.spec.pooling)
