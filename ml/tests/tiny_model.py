"""Tiny ONNX models and tokenizers, so tests need no download.

The embedding model looks up a fixed vector per token (like a real model's
first layer), which is enough to test tokenizing, batching, pooling and
prefixes. The reranker adds up a score per token; the OCR models see dark
pixels as text (see ``write_tiny_ocr``).
"""

from pathlib import Path

import numpy as np
import onnx
import yaml
from onnx import TensorProto, helper, numpy_helper
from tokenizers import Tokenizer, models, pre_tokenizers

from paperus_ml.models import ModelSpec, Part

WORDS = [
    "[UNK]",
    "[CLS]",
    "query:",
    "passage:",
    "drought",
    "rivers",
    "rain",
    "cooking",
    "pasta",
]
DIMENSIONS = 8


def ids_input(name: str) -> onnx.ValueInfoProto:
    return helper.make_tensor_value_info(name, TensorProto.INT64, ["b", "s"])


def save(graph: onnx.GraphProto, path: Path) -> None:
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, path)


def write_tokenizer(path: Path) -> None:
    tokenizer = Tokenizer(
        models.WordLevel({w: i for i, w in enumerate(WORDS)}, unk_token="[UNK]")
    )
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tokenizer.save(str(path))


def write_tiny_model(directory: Path, *, token_types: bool = False) -> ModelSpec:
    """``token_types``: the model also takes token types (and ignores them),
    as BERT-like models do."""
    rng = np.random.default_rng(0)
    table = rng.normal(size=(len(WORDS), DIMENSIONS)).astype(np.float32)
    inputs = [ids_input("input_ids"), ids_input("attention_mask")]
    if token_types:
        inputs.append(ids_input("token_type_ids"))
    graph = helper.make_graph(
        [helper.make_node("Gather", ["table", "input_ids"], ["last_hidden_state"])],
        "tiny",
        inputs=inputs,
        outputs=[
            helper.make_tensor_value_info(
                "last_hidden_state", TensorProto.FLOAT, ["b", "s", DIMENSIONS]
            )
        ],
        initializer=[numpy_helper.from_array(table, "table")],
    )
    save(graph, directory / "model.onnx")
    write_tokenizer(directory / "tokenizer.json")
    return ModelSpec(
        name="tiny",
        repo="local/tiny",
        revision="0",
        onnx_file="model.onnx",
        tokenizer_file="tokenizer.json",
        pooling="mean",
        dimensions=DIMENSIONS,
        max_tokens=16,
        query_prefix="query: ",
        passage_prefix="passage: ",
    )


# The reranker's score: the sum of a score per token of query and passage,
# plus one per passage token (token type 1).
WORD_SCORES = [0.5, 0.0, 0.0, 0.0, 3.0, 2.0, 1.0, -2.0, -1.0]
PASSAGE_TOKEN_SCORE = 1.0


def tiny_rerank_score(query: str, passage: str, max_tokens: int = 64) -> float:
    """What the tiny reranker scores, worked out by hand."""
    ids = [WORDS.index(w) if w in WORDS else 0 for w in query.split()]
    passage_ids = [WORDS.index(w) if w in WORDS else 0 for w in passage.split()]
    passage_ids = passage_ids[: max_tokens - len(ids)]
    tokens = [*ids, *passage_ids]
    return sum(WORD_SCORES[i] for i in tokens) + PASSAGE_TOKEN_SCORE * len(passage_ids)


def write_tiny_reranker(directory: Path, max_tokens: int = 64) -> ModelSpec:
    nodes = [
        helper.make_node("Gather", ["word_scores", "input_ids"], ["words"]),
        helper.make_node("Cast", ["token_type_ids"], ["types"], to=TensorProto.FLOAT),
        helper.make_node("Mul", ["types", "passage_score"], ["passage"]),
        helper.make_node("Add", ["words", "passage"], ["tokens"]),
        helper.make_node("Cast", ["attention_mask"], ["mask"], to=TensorProto.FLOAT),
        helper.make_node("Mul", ["tokens", "mask"], ["masked"]),
        helper.make_node("ReduceSum", ["masked", "axes"], ["logits"], keepdims=1),
    ]
    graph = helper.make_graph(
        nodes,
        "tiny-reranker",
        inputs=[
            ids_input("input_ids"),
            ids_input("attention_mask"),
            ids_input("token_type_ids"),
        ],
        outputs=[helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["b", 1])],
        initializer=[
            numpy_helper.from_array(np.array(WORD_SCORES, np.float32), "word_scores"),
            numpy_helper.from_array(
                np.array(PASSAGE_TOKEN_SCORE, np.float32), "passage_score"
            ),
            numpy_helper.from_array(np.array([1], np.int64), "axes"),
        ],
    )
    save(graph, directory / "reranker.onnx")
    write_tokenizer(directory / "tokenizer.json")
    return ModelSpec(
        name="tiny-reranker",
        repo="local/tiny-reranker",
        revision="0",
        onnx_file="reranker.onnx",
        tokenizer_file="tokenizer.json",
        pooling="cls",
        dimensions=1,
        max_tokens=max_tokens,
        task="rerank",
    )


def write_tiny_ocr(directory: Path) -> ModelSpec:
    """OCR models that see dark pixels as text, writing "x" for each dark
    block of a line: the detector marks dark pixels, smeared sideways so the
    blocks of a line join; the reader writes "x" where a column of its line
    is dark (more than half), else CTC's blank."""
    channels = [1, 3, 1, 1]
    detector = helper.make_graph(
        [
            # Back from ImageNet's normalization to 0..1, then darkness.
            helper.make_node("Mul", ["x", "std"], ["scaled"]),
            helper.make_node("Add", ["scaled", "mean"], ["pixels"]),
            helper.make_node("ReduceMean", ["pixels"], ["gray"], axes=[1]),
            helper.make_node("Sub", ["one", "gray"], ["dark"]),
            helper.make_node(
                "MaxPool",
                ["dark"],
                ["smeared"],
                kernel_shape=[1, 15],
                pads=[0, 7, 0, 7],
            ),
            helper.make_node("Mul", ["smeared", "four"], ["strong"]),
            helper.make_node("Clip", ["strong", "zero", "one"], ["probabilities"]),
        ],
        "tiny-detector",
        inputs=[
            helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, "h", "w"])
        ],
        outputs=[
            helper.make_tensor_value_info(
                "probabilities", TensorProto.FLOAT, [1, 1, "h", "w"]
            )
        ],
        initializer=[
            numpy_helper.from_array(
                np.array([0.229, 0.224, 0.225], np.float32).reshape(channels), "std"
            ),
            numpy_helper.from_array(
                np.array([0.485, 0.456, 0.406], np.float32).reshape(channels), "mean"
            ),
            numpy_helper.from_array(np.array(1, np.float32), "one"),
            numpy_helper.from_array(np.array(0, np.float32), "zero"),
            numpy_helper.from_array(np.array(4, np.float32), "four"),
        ],
    )
    (directory / "det").mkdir(exist_ok=True)
    save(detector, directory / "det" / "detector.onnx")

    reader = helper.make_graph(
        [
            # Back from (pixel - 0.5) / 0.5 to 0..1, then darkness per column.
            helper.make_node("Mul", ["x", "half"], ["scaled"]),
            helper.make_node("Add", ["scaled", "half"], ["pixels"]),
            helper.make_node("ReduceMean", ["pixels"], ["gray"], axes=[1]),
            helper.make_node("Sub", ["one", "gray"], ["dark"]),
            helper.make_node("ReduceMax", ["dark"], ["column"], axes=[2], keepdims=0),
            # Steps of 4 columns: [blank, "x", " "] per step.
            helper.make_node(
                "AveragePool", ["column"], ["step"], kernel_shape=[4], strides=[4]
            ),
            # The blank wins ties (the gray padding of a batch).
            helper.make_node("Sub", ["blank_bias", "step"], ["blank"]),
            helper.make_node("Mul", ["step", "zero"], ["space"]),
            helper.make_node("Concat", ["blank", "step", "space"], ["classes"], axis=1),
            helper.make_node("Transpose", ["classes"], ["steps"], perm=[0, 2, 1]),
        ],
        "tiny-reader",
        inputs=[
            helper.make_tensor_value_info("x", TensorProto.FLOAT, ["n", 3, 48, "w"])
        ],
        outputs=[
            helper.make_tensor_value_info("steps", TensorProto.FLOAT, ["n", "t", 3])
        ],
        initializer=[
            numpy_helper.from_array(np.array(0.5, np.float32), "half"),
            numpy_helper.from_array(np.array(1, np.float32), "one"),
            numpy_helper.from_array(np.array(0, np.float32), "zero"),
            numpy_helper.from_array(np.array(1.02, np.float32), "blank_bias"),
        ],
    )
    save(reader, directory / "reader.onnx")
    settings = {"PostProcess": {"name": "CTCLabelDecode", "character_dict": ["x"]}}
    (directory / "reader.yml").write_text(yaml.safe_dump(settings))
    return ModelSpec(
        name="tiny-ocr",
        repo="local/tiny-ocr",
        revision="0",
        onnx_file="reader.onnx",
        tokenizer_file="reader.yml",
        pooling="cls",
        dimensions=0,
        max_tokens=0,
        task="ocr",
        detector=Part(
            repo="local/tiny-detector",
            revision="0",
            onnx_file="detector.onnx",
            folder="det",
        ),
    )
