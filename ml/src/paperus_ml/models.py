"""The models paperus-ml can serve.

Each is an ONNX export from Hugging Face, pinned to a revision so a changed
file upstream cannot silently change the vectors stored in paperus.
"""

from dataclasses import dataclass
from typing import Literal

Pooling = Literal["cls", "mean"]
Kind = Literal["query", "passage"]


@dataclass(frozen=True)
class ModelSpec:
    name: str
    repo: str
    revision: str
    onnx_file: str
    tokenizer_file: str
    pooling: Pooling
    dimensions: int
    max_tokens: int
    query_prefix: str = ""
    passage_prefix: str = ""

    def prefix(self, kind: Kind) -> str:
        return self.query_prefix if kind == "query" else self.passage_prefix


MODELS = {
    spec.name: spec
    for spec in [
        # Multilingual, 1024 dimensions, long inputs; ONNX from the authors.
        ModelSpec(
            name="bge-m3",
            repo="BAAI/bge-m3",
            revision="5617a9f61b028005a4858fdac845db406aefb181",
            onnx_file="onnx/model.onnx",
            tokenizer_file="onnx/tokenizer.json",
            pooling="cls",
            dimensions=1024,
            max_tokens=8192,
        ),
        # Small and fast (int8, 118 MB); for development and small machines.
        ModelSpec(
            name="multilingual-e5-small",
            repo="Xenova/multilingual-e5-small",
            revision="761b726dd34fb83930e26aab4e9ac3899aa1fa78",
            onnx_file="onnx/model_quantized.onnx",
            tokenizer_file="tokenizer.json",
            pooling="mean",
            dimensions=384,
            max_tokens=512,
            query_prefix="query: ",
            passage_prefix="passage: ",
        ),
    ]
}
