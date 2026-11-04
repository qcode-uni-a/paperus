"""A tiny ONNX "embedding model" and tokenizer, so tests need no download.

The model looks up a fixed vector per token (like a real model's first
layer), which is enough to test tokenizing, batching, pooling and prefixes.
"""

from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
from tokenizers import Tokenizer, models, pre_tokenizers

from paperus_ml.models import ModelSpec

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


def write_tiny_model(directory: Path) -> ModelSpec:
    rng = np.random.default_rng(0)
    table = rng.normal(size=(len(WORDS), DIMENSIONS)).astype(np.float32)
    graph = helper.make_graph(
        [helper.make_node("Gather", ["table", "input_ids"], ["last_hidden_state"])],
        "tiny",
        inputs=[
            helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["b", "s"]),
            helper.make_tensor_value_info(
                "attention_mask", TensorProto.INT64, ["b", "s"]
            ),
        ],
        outputs=[
            helper.make_tensor_value_info(
                "last_hidden_state", TensorProto.FLOAT, ["b", "s", DIMENSIONS]
            )
        ],
        initializer=[numpy_helper.from_array(table, "table")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.save(model, directory / "model.onnx")

    tokenizer = Tokenizer(
        models.WordLevel({w: i for i, w in enumerate(WORDS)}, unk_token="[UNK]")
    )
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tokenizer.save(str(directory / "tokenizer.json"))
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
