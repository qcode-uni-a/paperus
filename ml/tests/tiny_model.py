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


TABLE = (
    np.random.default_rng(0).normal(size=(len(WORDS), DIMENSIONS)).astype(np.float32)
)


def write_tiny_model(
    directory: Path,
    *,
    token_types: bool = False,
    decoder: bool = False,
    sentence_output: bool = False,
) -> ModelSpec:
    """``token_types``: the model also takes token types (and ignores them),
    as BERT-like models do; ``decoder``: token positions and what came
    before (``past_key_values.0.*``, ignored), as decoders exported for
    generating text do; ``sentence_output``: also its own sentence vectors
    (``sentence_embedding``: the mean of the token vectors)."""
    inputs = [ids_input("input_ids"), ids_input("attention_mask")]
    if token_types:
        inputs.append(ids_input("token_type_ids"))
    if decoder:
        inputs.append(ids_input("position_ids"))
        inputs += [
            helper.make_tensor_value_info(
                f"past_key_values.0.{part}",
                TensorProto.FLOAT,
                ["batch_size", 2, "p", 4],
            )
            for part in ("key", "value")
        ]
    if sentence_output:
        # As EmbeddingGemma 2: an image's features, empty for a text alone.
        inputs.append(
            helper.make_tensor_value_info(
                "image_features", TensorProto.FLOAT, ["num_image_tokens", 4]
            )
        )
    nodes = [helper.make_node("Gather", ["table", "input_ids"], ["last_hidden_state"])]
    outputs = [
        helper.make_tensor_value_info(
            "last_hidden_state", TensorProto.FLOAT, ["b", "s", DIMENSIONS]
        )
    ]
    if sentence_output:
        nodes.append(
            helper.make_node(
                "ReduceMean",
                ["last_hidden_state"],
                ["sentence_embedding"],
                axes=[1],
                keepdims=0,
            )
        )
        outputs.append(
            helper.make_tensor_value_info(
                "sentence_embedding", TensorProto.FLOAT, ["b", DIMENSIONS]
            )
        )
    graph = helper.make_graph(
        nodes,
        "tiny",
        inputs=inputs,
        outputs=outputs,
        initializer=[numpy_helper.from_array(TABLE, "table")],
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


# A tiny Qwen3-VL pair (paperus_ml.qwen3_vl): the vision encoder turns each
# block of 2 by 2 patches into one token by a matrix product; the decoders
# add up all tokens (plus their first DeepStack features): the embedding
# model normalized, the reranker the sum of that as the score.
VL_DIMENSIONS = 8
VL_SPECIAL = {
    "<|endoftext|>": 151643,
    "<|im_start|>": 151644,
    "<|im_end|>": 151645,
    "<|vision_start|>": 151652,
    "<|vision_end|>": 151653,
    "<|image_pad|>": 151655,
}


def _value(name: str, kind: int, shape: list[str | int]) -> onnx.ValueInfoProto:
    return helper.make_tensor_value_info(name, kind, shape)


def write_tiny_qwen3_vl(directory: Path) -> tuple[ModelSpec, ModelSpec]:
    """The pair's files in their layout; their specs (embedding, reranker)."""
    rng = np.random.default_rng(1)
    shared = directory / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    f16 = TensorProto.FLOAT16
    vision = helper.make_graph(
        [
            helper.make_node("Reshape", ["pixel_values", "merged_shape"], ["merged"]),
            helper.make_node("MatMul", ["merged", "w"], ["image_features"]),
            helper.make_node("Unsqueeze", ["image_features", "zero"], ["one"]),
            helper.make_node(
                "Concat", ["one", "one", "one"], ["deepstack_features"], axis=0
            ),
        ],
        "tiny_vision",
        inputs=[
            _value("pixel_values", f16, ["p", 1536]),
            _value("interp_indices", TensorProto.INT64, ["p", 4]),
            _value("interp_weights", f16, ["p", 4]),
            _value("position_ids", TensorProto.INT64, ["p", 2]),
        ],
        outputs=[
            _value("image_features", f16, ["t", VL_DIMENSIONS]),
            _value("deepstack_features", f16, [3, "t", VL_DIMENSIONS]),
        ],
        initializer=[
            numpy_helper.from_array(np.array([-1, 4 * 1536], np.int64), "merged_shape"),
            numpy_helper.from_array(
                (rng.normal(size=(4 * 1536, VL_DIMENSIONS)) / 50).astype(np.float16),
                "w",
            ),
            numpy_helper.from_array(np.array([0], np.int64), "zero"),
        ],
    )
    save(vision, shared / "vision_encoder_fp16.onnx")
    np.save(
        shared / "embed_tokens_fp16.npy",
        rng.normal(size=(151656, VL_DIMENSIONS)).astype(np.float16),
    )
    words = {w: i for i, w in enumerate(WORDS)} | VL_SPECIAL
    tokenizer = Tokenizer(models.WordLevel(words, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tokenizer.add_special_tokens(list(VL_SPECIAL))
    tokenizer.save(str(shared / "tokenizer.json"))

    specs = []
    for task, folder in (("embedding", "embedding"), ("rerank", "reranker")):
        (directory / folder).mkdir(exist_ok=True)
        nodes = [
            helper.make_node("Gather", ["deepstack", "first"], ["layer"], axis=0),
            helper.make_node("Add", ["inputs_embeds", "layer"], ["tokens16"]),
            helper.make_node("Cast", ["tokens16"], ["tokens"], to=TensorProto.FLOAT),
            # All tokens' sum: padding (zeros) changes nothing.
            helper.make_node("ReduceSum", ["tokens", "axis"], ["sum"], keepdims=0),
        ]
        if task == "embedding":
            nodes += [
                helper.make_node("ReduceL2", ["sum"], ["norm"], axes=[1], keepdims=1),
                helper.make_node("Div", ["sum", "norm"], ["embedding"]),
            ]
            output = _value("embedding", TensorProto.FLOAT, ["b", VL_DIMENSIONS])
        else:
            nodes.append(
                helper.make_node("ReduceSum", ["sum", "axis"], ["score"], keepdims=0)
            )
            output = _value("score", TensorProto.FLOAT, ["b"])
        decoder = helper.make_graph(
            nodes,
            f"tiny_{folder}",
            inputs=[
                _value("inputs_embeds", f16, ["b", "s", VL_DIMENSIONS]),
                _value("attention_mask", TensorProto.INT64, ["b", "s"]),
                _value("position_ids", TensorProto.INT64, [3, "b", "s"]),
                _value("deepstack", f16, [3, "b", "s", VL_DIMENSIONS]),
            ],
            outputs=[output],
            initializer=[
                numpy_helper.from_array(np.array(0, np.int64), "first"),
                numpy_helper.from_array(np.array([1], np.int64), "axis"),
            ],
        )
        save(decoder, directory / folder / "decoder.onnx")
        specs.append(
            ModelSpec(
                name=f"tiny-vl-{folder}",
                repo="local/tiny-vl",
                revision="0",
                onnx_file=f"{folder}/decoder.onnx",
                tokenizer_file="shared/tokenizer.json",
                pooling="last",
                dimensions=VL_DIMENSIONS,
                max_tokens=1024,
                task=task,
                layout="qwen3-vl",
                images=True,
            )
        )
    return specs[0], specs[1]
