"""Running an embedding model with ONNX Runtime."""

import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import onnxruntime
from tokenizers import Encoding, Tokenizer

from paperus_ml import metrics
from paperus_ml.device import CUDA, Device, providers, run_options
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


def open_session(
    path: Path, intra_op_threads: int, device: Device
) -> tuple[onnxruntime.InferenceSession, Device]:
    """The model file in ONNX Runtime, and where it actually runs: ONNX
    Runtime falls back to the CPU when the GPU cannot be used."""
    session = onnxruntime.InferenceSession(
        str(path),
        sess_options=session_options(intra_op_threads),
        providers=providers(device),
    )
    return session, "cuda" if session.get_providers()[0] == CUDA else "cpu"


def open_tokenizer(path: Path, max_tokens: int) -> Tokenizer:
    """Truncating to what the model reads; padding is done per batch."""
    tokenizer = Tokenizer.from_file(str(path))
    tokenizer.enable_truncation(max_tokens)
    tokenizer.no_padding()
    return tokenizer


def model_inputs(
    encodings: Sequence[Encoding], input_names: set[str]
) -> dict[str, npt.NDArray[np.int64]]:
    """Token ids padded to the longest, the attention mask, and the token
    types (query or passage) for models that take them."""
    width = max(len(e.ids) for e in encodings)
    ids = np.zeros((len(encodings), width), dtype=np.int64)
    mask = np.zeros_like(ids)
    types = np.zeros_like(ids)
    for row, encoding in enumerate(encodings):
        ids[row, : len(encoding.ids)] = encoding.ids
        mask[row, : len(encoding.ids)] = 1
        types[row, : len(encoding.ids)] = encoding.type_ids
    feed = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in input_names:
        feed["token_type_ids"] = types
    if "position_ids" in input_names:
        feed["position_ids"] = np.broadcast_to(np.arange(width), ids.shape).copy()
    return feed


def pool(
    hidden: npt.NDArray[np.float32],
    mask: npt.NDArray[np.int64],
    how: str,
) -> Vectors:
    """Sentence vectors from token vectors, L2-normalized."""
    if how == "cls":
        vectors = hidden[:, 0]
    elif how == "last":
        # Padding on the right: each text's last real token.
        last = np.maximum(mask.sum(axis=1) - 1, 0)
        vectors = hidden[np.arange(len(hidden)), last]
    elif how == "output":
        vectors = hidden  # the model's own sentence vectors
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
        self.tokenizer = open_tokenizer(
            model_dir / spec.tokenizer_file, spec.max_tokens
        )
        self.session, self.device = open_session(
            model_dir / spec.onnx_file_for(device), intra_op_threads, device
        )
        self.input_names = {i.name for i in self.session.get_inputs()}
        # Inputs besides the text's, given empty: what came before, for
        # decoders exported for generating text (past_key_values.*), and
        # the features of images, video and sound for models that take them
        # with the text (EmbeddingGemma 2): none, for a text alone.
        self.empty = {
            i.name: (
                [
                    "batch" if "batch" in str(d) else d if isinstance(d, int) else 0
                    for d in i.shape
                ],
                np.float16 if "float16" in i.type else np.float32,
            )
            for i in self.session.get_inputs()
            if "float" in i.type
        }
        # The model's own sentence vectors (pooling "output"), else the
        # token vectors (its first output).
        outputs = [o.name for o in self.session.get_outputs()]
        self.output = (
            "sentence_embedding"
            if spec.pooling == "output" and "sentence_embedding" in outputs
            else outputs[0]
        )
        self.run_options = run_options(self.device)
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
        feed: dict[str, npt.NDArray[Any]] = dict(
            model_inputs(encodings, self.input_names)
        )
        for name, (shape, dtype) in self.empty.items():
            size = [len(encodings) if d == "batch" else int(d) for d in shape]
            feed[name] = np.zeros(size, dtype=dtype)
        with self.running:
            started = time.perf_counter()
            hidden = self.session.run([self.output], feed, self.run_options)[0]
            metrics.BATCH_SECONDS.labels(self.spec.name).observe(
                time.perf_counter() - started
            )
        return pool(
            np.asarray(hidden, dtype=np.float32),
            feed["attention_mask"],
            self.spec.pooling,
        )
