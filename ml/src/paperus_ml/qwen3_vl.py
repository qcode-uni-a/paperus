"""Qwen3-VL's inputs, prepared without PyTorch: an image as the vision
encoder's patches, what depends on the image's grid (the interpolated
position embedding, the rotary positions), and the language model's three
positions per token (time, row, column).

Ported from Hugging Face transformers (Apache-2.0: the Qwen2-VL image
processor's ``smart_resize`` and patch layout, ``vision_utils`` and
Qwen3-VL's ``get_rope_index``); see THIRD_PARTY.md.
"""

import math
import threading
import time
import weakref
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
from tokenizers import Tokenizer

from paperus_ml import metrics
from paperus_ml.device import Device, run_options
from paperus_ml.encoder import open_session
from paperus_ml.models import Kind, ModelSpec

PATCH = 16
MERGE = 2
TEMPORAL = 2
"""An image is a video of two equal frames."""
FACTOR = PATCH * MERGE
MIN_PIXELS = 4096
MAX_PIXELS = 1_310_720
GRID_SIDE = 48
"""The learned position embeddings: a 48 by 48 grid, resampled to each image."""
MAX_ASPECT = 200


@dataclass
class Image:
    """One image ready for the vision encoder."""

    pixels: npt.NDArray[np.float16]
    """``(patches, 3 · 2 · 16 · 16)``, normalized to [-1, 1]."""
    grid: tuple[int, int]
    """Patches down and across (each a multiple of ``MERGE``)."""

    @property
    def tokens(self) -> int:
        """How many tokens the language model gets for it."""
        return self.grid[0] * self.grid[1] // (MERGE * MERGE)


def smart_resize(height: int, width: int) -> tuple[int, int]:
    """The size an image is resized to: both sides multiples of ``FACTOR``,
    its area within ``MIN_PIXELS`` and ``MAX_PIXELS``, its shape kept."""
    if max(height, width) / max(min(height, width), 1) > MAX_ASPECT:
        raise ValueError(f"an image at most {MAX_ASPECT} times as long as wide")
    h = round(height / FACTOR) * FACTOR
    w = round(width / FACTOR) * FACTOR
    if h * w > MAX_PIXELS:
        beta = math.sqrt(height * width / MAX_PIXELS)
        h = max(FACTOR, math.floor(height / beta / FACTOR) * FACTOR)
        w = max(FACTOR, math.floor(width / beta / FACTOR) * FACTOR)
    elif h * w < MIN_PIXELS:
        beta = math.sqrt(MIN_PIXELS / (height * width))
        h = math.ceil(height * beta / FACTOR) * FACTOR
        w = math.ceil(width * beta / FACTOR) * FACTOR
    return h, w


def prepare(rgb: npt.NDArray[np.uint8]) -> Image:
    """An RGB image (height by width by 3) as the vision encoder's patches."""
    height, width = rgb.shape[:2]
    h, w = smart_resize(height, width)
    if (h, w) != (height, width):
        # Area averaging when shrinking (no aliasing), cubic when enlarging.
        shrinking = h * w < height * width
        interpolation = cv2.INTER_AREA if shrinking else cv2.INTER_CUBIC
        rgb = np.asarray(cv2.resize(rgb, (w, h), interpolation=interpolation), np.uint8)
    image = rgb.astype(np.float32) / 255 * 2 - 1  # mean and spread 0.5
    gh, gw = h // PATCH, w // PATCH
    patches = image.transpose(2, 0, 1).reshape(
        3, gh // MERGE, MERGE, PATCH, gw // MERGE, MERGE, PATCH
    )
    # Blocks of MERGE by MERGE patches; per patch its channels, each over the
    # two (equal) frames, each PATCH by PATCH.
    patches = patches.transpose(1, 4, 2, 5, 0, 3, 6)[:, :, :, :, :, None]
    patches = np.broadcast_to(
        patches, (*patches.shape[:5], TEMPORAL, PATCH, PATCH)
    ).reshape(gh * gw, 3 * TEMPORAL * PATCH * PATCH)
    return Image(patches.astype(np.float16), (gh, gw))


def _block_order(gh: int, gw: int) -> tuple[npt.NDArray[np.int64], ...]:
    """Each patch's row and column, in the encoder's order (blocks of
    ``MERGE`` by ``MERGE`` patches)."""
    within = np.arange(gh * gw)
    blocks_w = gw // MERGE
    in_col = within % MERGE
    in_row = (within // MERGE) % MERGE
    block_col = (within // (MERGE * MERGE)) % blocks_w
    block_row = within // (MERGE * MERGE * blocks_w)
    return block_row * MERGE + in_row, block_col * MERGE + in_col


def _taps(
    index: npt.NDArray[np.int64], size: int
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float32]]:
    """Bilinear taps (with corners aligned) into the learned grid along one
    axis of ``size`` patches, and their weights."""
    src = index.astype(np.float32) * (GRID_SIDE - 1) / max(size - 1, 1)
    floor = np.floor(src)
    offsets = np.arange(2)
    taps = np.clip(floor.astype(np.int64)[:, None] + offsets, 0, GRID_SIDE - 1)
    weights = np.clip(1 - np.abs(src[:, None] - floor[:, None] - offsets), 0, None)
    return taps, weights.astype(np.float32)


def grid_inputs(image: Image) -> dict[str, npt.NDArray[np.generic]]:
    """The vision encoder's inputs besides the pixels: how its learned
    position grid is resampled to the image (four taps a patch) and each
    patch's row and column for the rotary embedding."""
    gh, gw = image.grid
    row, col = _block_order(gh, gw)
    h_taps, h_weights = _taps(row, gh)
    w_taps, w_weights = _taps(col, gw)
    indices = (h_taps[:, :, None] * GRID_SIDE + w_taps[:, None, :]).reshape(-1, 4)
    weights = (h_weights[:, :, None] * w_weights[:, None, :]).reshape(-1, 4)
    return {
        "pixel_values": image.pixels,
        "interp_indices": indices,
        "interp_weights": weights.astype(np.float16),
        "position_ids": np.stack([row, col], axis=-1).astype(np.int64),
    }


def positions(
    pieces: list[int | tuple[int, int]],
) -> npt.NDArray[np.int64]:
    """The language model's positions ``(3, tokens)`` for a sequence of text
    and images: an ``int`` is that many text tokens, a pair an image's grid
    (patches down and across). Text counts on in all three; an image's tokens
    get their row and column (offset by the text before them), and the text
    after it goes on from the longer of its sides."""
    out = []
    at = 0
    for piece in pieces:
        if isinstance(piece, int):
            out.append(np.broadcast_to(np.arange(at, at + piece), (3, piece)))
            at += piece
            continue
        rows, cols = piece[0] // MERGE, piece[1] // MERGE
        r, c = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
        out.append(np.stack([np.full(rows * cols, at), r.ravel() + at, c.ravel() + at]))
        at += max(rows, cols)
    return np.concatenate(out, axis=1).astype(np.int64)


# Running the models: the token sequences as the originals build them
# (sentence-transformers 5.4 with the models' chat templates), the image
# features in place of the image tokens, the DeepStack features spread over
# the sequence (zeros at text), padding on the left.

IM_START, IM_END, END_OF_TEXT = 151644, 151645, 151643
VISION_START, VISION_END, IMAGE_PAD = 151652, 151653, 151655
EMBED_INSTRUCTION = "Represent the user's input."
RERANK_SYSTEM = (
    "Judge whether the Document meets the requirements based on the Query and "
    'the Instruct provided. Note that the answer can only be "yes" or "no".'
)
MAX_TEXT_TOKENS = 1024
"""A text's tokens kept (passages are a few hundred)."""
MAX_BATCH_TOKENS = 4096
"""Tokens in one batch at most (padding counted): a 2B model's attention
for more does not fit next to both models on an 8 GB card (the service's
setting is for small text models)."""


@dataclass
class Item:
    """A passage, a figure, or both (a figure with its caption)."""

    text: str = ""
    image: Image | None = None


Piece = list[int] | Image
"""Token ids, or an image (as many tokens as ``Image.tokens``)."""


def _flatten(pieces: list[Piece]) -> tuple[list[int], list[int | tuple[int, int]]]:
    """The ids (image tokens as placeholders) and the runs ``positions`` takes."""
    ids: list[int] = []
    runs: list[int | tuple[int, int]] = []
    for piece in pieces:
        if isinstance(piece, Image):
            ids += [IMAGE_PAD] * piece.tokens
            runs.append(piece.grid)
        else:
            ids += piece
            if runs and isinstance(runs[-1], int):
                runs[-1] += len(piece)
            else:
                runs.append(len(piece))
    return ids, runs


def batch_inputs(
    sequences: list[list[Piece]],
    table: npt.NDArray[np.float16],
    features: dict[int, tuple[npt.NDArray[np.float16], npt.NDArray[np.float16]]],
) -> dict[str, npt.NDArray[np.generic]]:
    """The decoder's inputs for sequences padded on the left: token vectors
    (an image's features at its tokens), mask, positions, DeepStack features.
    ``features``: per image (by ``id``), its features and DeepStack features."""
    flat = [_flatten(s) for s in sequences]
    width = max(len(ids) for ids, _ in flat)
    rows, dims = len(sequences), table.shape[1]
    embeds = np.zeros((rows, width, dims), dtype=np.float16)
    deep = np.zeros((3, rows, width, dims), dtype=np.float16)
    mask = np.zeros((rows, width), dtype=np.int64)
    pos = np.ones((3, rows, width), dtype=np.int64)
    for row, (sequence, (ids, runs)) in enumerate(zip(sequences, flat, strict=True)):
        start = width - len(ids)
        embeds[row, start:] = table[np.asarray(ids)]
        mask[row, start:] = 1
        pos[:, row, start:] = positions(runs)
        at = start
        for piece in sequence:
            if isinstance(piece, Image):
                image_features, deepstack = features[id(piece)]
                embeds[row, at : at + piece.tokens] = image_features
                deep[:, row, at : at + piece.tokens] = deepstack
                at += piece.tokens
            else:
                at += len(piece)
    return {
        "inputs_embeds": embeds,
        "attention_mask": mask,
        "position_ids": pos,
        "deepstack": deep,
    }


class _Shared:
    """The vision encoder, token table and tokenizer both models use."""

    def __init__(self, directory: Path, intra_op_threads: int, device: Device) -> None:
        shared = directory / "shared"
        self.vision, self.device = open_session(
            shared / "vision_encoder_fp16.onnx", intra_op_threads, device
        )
        self.table = np.load(shared / "embed_tokens_fp16.npy", mmap_mode="r")
        self.tokenizer = Tokenizer.from_file(str(shared / "tokenizer.json"))


_shared: weakref.WeakValueDictionary[tuple[str, ...], _Shared] = (
    weakref.WeakValueDictionary()
)
"""Loaded once while either model of a pair is (same files, same device)."""
_shared_lock = threading.Lock()


def _shared_parts(
    key: tuple[str, ...], directory: Path, intra_op_threads: int, device: Device
) -> _Shared:
    with _shared_lock:
        found = _shared.get(key)
        if found is None:
            found = _Shared(directory, intra_op_threads, device)
            _shared[key] = found
        return found


class Runtime:
    """One of the pair, from the model's download: the shared vision encoder,
    token table and tokenizer (``shared/``) and the task's decoder
    (``decoder_file``, e.g. ``embedding/decoder_int8.onnx``)."""

    def __init__(
        self,
        directory: Path,
        decoder_file: str,
        *,
        intra_op_threads: int = 0,
        device: Device = "cpu",
        max_batch_tokens: int = 8192,
        shared_key: tuple[str, ...] | None = None,
    ) -> None:
        """``shared_key``: models with the same key (repository, revision,
        device) share the vision encoder, table and tokenizer."""
        key = shared_key or (str(directory), str(intra_op_threads), device)
        self.shared = _shared_parts(key, directory, intra_op_threads, device)
        self.vision, self.device = self.shared.vision, self.shared.device
        # Each run's working memory given back afterwards (as other models).
        self.run_options = run_options(self.device)
        self.decoder, _ = open_session(
            directory / decoder_file, intra_op_threads, device
        )
        self.table, self.tokenizer = self.shared.table, self.shared.tokenizer
        self.max_batch_tokens = max_batch_tokens

    def tokens(self, text: str, limit: int | None = None) -> list[int]:
        ids = self.tokenizer.encode(text, add_special_tokens=False).ids
        return ids[:limit] if limit else ids

    def _content(self, item: Item) -> list[Piece]:
        pieces: list[Piece] = []
        if item.image is not None:
            pieces += [[VISION_START], item.image, [VISION_END]]
        if item.text:
            pieces.append(self.tokens(item.text, MAX_TEXT_TOKENS))
        return pieces

    def _features(
        self, sequences: list[list[Piece]]
    ) -> dict[int, tuple[npt.NDArray[np.float16], npt.NDArray[np.float16]]]:
        found: dict[int, tuple[npt.NDArray[np.float16], npt.NDArray[np.float16]]] = {}
        for sequence in sequences:
            for piece in sequence:
                if isinstance(piece, Image) and id(piece) not in found:
                    features, deepstack = self.vision.run(
                        None, grid_inputs(piece), self.run_options
                    )
                    found[id(piece)] = (np.asarray(features), np.asarray(deepstack))
        return found

    def _run(self, sequences: list[list[Piece]]) -> npt.NDArray[np.float32]:
        """The decoder's output per sequence, in batches of similar length."""
        lengths = [len(_flatten(s)[0]) for s in sequences]
        features = self._features(sequences)
        out: list[npt.NDArray[np.float32] | None] = [None] * len(sequences)
        order = sorted(range(len(sequences)), key=lambda i: lengths[i])
        batch: list[int] = []
        for index in [*order, None]:
            full = index is None or (
                batch and (len(batch) + 1) * lengths[index] > self.max_batch_tokens
            )
            if full and batch:
                feeds = batch_inputs(
                    [sequences[i] for i in batch], self.table, features
                )
                result = np.asarray(self.decoder.run(None, feeds, self.run_options)[0])
                for i, value in zip(batch, list(result), strict=True):
                    out[i] = np.asarray(value, dtype=np.float32)
                batch = []
            if index is not None:
                batch.append(index)
        return np.stack([o for o in out if o is not None])

    def embed(
        self, items: list[Item], instruction: str = EMBED_INSTRUCTION
    ) -> npt.NDArray[np.float32]:
        """Normalized vectors (``instruction``: for queries, what they look for)."""
        head = self.tokens(
            f"<|im_start|>system\n{instruction}<|im_end|>\n<|im_start|>user\n"
        )
        tail = [*self.tokens("<|im_end|>\n<|im_start|>assistant\n"), END_OF_TEXT]
        return self._run([[head, *self._content(item), tail] for item in items])

    def score(self, query: str, items: list[Item], instruction: str) -> list[float]:
        """How well each item answers ``query``: the yes-minus-no logit."""
        head = self.tokens(
            f"<|im_start|>system\n{RERANK_SYSTEM}<|im_end|>\n<|im_start|>user\n"
            f"<Instruct>: {instruction}<Query>:{query}\n<Document>:"
        )
        tail = self.tokens("<|im_end|>\n<|im_start|>assistant\n")
        scores = self._run([[head, *self._content(item), tail] for item in items])
        return [float(s) for s in scores]


QUERY_INSTRUCTION = (
    "Retrieve figures or passages from scientific papers relevant to the query."
)
"""What a query looks for (queries get it, passages and figures the models'
default)."""


def decode(data: bytes) -> Image:
    """An image file (PNG, JPEG, …) ready for the vision encoder; ValueError
    if it is none."""
    found = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if found is None:
        raise ValueError("not an image")
    return prepare(np.ascontiguousarray(found[:, :, ::-1], dtype=np.uint8))  # to RGB


class MultimodalEncoder:
    """Qwen3-VL-Embedding as the service's other embedding models, with
    figures too (``embed_items``)."""

    def __init__(
        self,
        spec: ModelSpec,
        model_dir: Path,
        *,
        intra_op_threads: int = 0,
        max_batch_texts: int = 32,  # (it batches by tokens)
        max_batch_tokens: int = 16384,
        device: Device = "cpu",
    ) -> None:
        self.spec = spec
        self.runtime = Runtime(
            model_dir,
            spec.onnx_file_for(device),
            intra_op_threads=intra_op_threads,
            device=device,
            max_batch_tokens=min(max_batch_tokens, MAX_BATCH_TOKENS),
            shared_key=(spec.repo, spec.revision, str(intra_op_threads), device),
        )
        self.device = self.runtime.device
        self.running = threading.RLock()

    def embed(self, texts: Sequence[str], kind: Kind) -> npt.NDArray[np.float32]:
        return self.embed_items([Item(text=t) for t in texts], kind)

    def embed_items(self, items: list[Item], kind: Kind) -> npt.NDArray[np.float32]:
        instruction = QUERY_INSTRUCTION if kind == "query" else EMBED_INSTRUCTION
        with self.running:
            started = time.perf_counter()
            vectors = self.runtime.embed(items, instruction)
            metrics.BATCH_SECONDS.labels(self.spec.name).observe(
                time.perf_counter() - started
            )
        return vectors


class MultimodalReranker:
    """Qwen3-VL-Reranker as the service's other rerankers, with figures too
    (``score_items``)."""

    def __init__(
        self,
        spec: ModelSpec,
        model_dir: Path,
        *,
        intra_op_threads: int = 0,
        max_batch_texts: int = 32,  # (it batches by tokens)
        max_batch_tokens: int = 16384,
        device: Device = "cpu",
    ) -> None:
        self.spec = spec
        self.runtime = Runtime(
            model_dir,
            spec.onnx_file_for(device),
            intra_op_threads=intra_op_threads,
            device=device,
            max_batch_tokens=min(max_batch_tokens, MAX_BATCH_TOKENS),
            shared_key=(spec.repo, spec.revision, str(intra_op_threads), device),
        )
        self.device = self.runtime.device
        self.running = threading.RLock()

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        return self.score_items(query, [Item(text=p) for p in passages])

    def score_items(self, query: str, items: list[Item]) -> list[float]:
        with self.running:
            started = time.perf_counter()
            scores = self.runtime.score(query, items, QUERY_INSTRUCTION)
            metrics.BATCH_SECONDS.labels(self.spec.name).observe(
                time.perf_counter() - started
            )
        return scores
