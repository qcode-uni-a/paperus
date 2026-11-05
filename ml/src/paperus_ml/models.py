"""The models paperus-ml can serve.

Each is an ONNX export from Hugging Face, pinned to a revision so a changed
file upstream cannot silently change the vectors stored in paperus.

Scores are the published retrieval averages of the full-precision models
(int8 exports typically lose about a point), checked 2026-11-05: MTEB
(eng, v2) and MTEB (deu, v1) Retrieval from the MTEB leaderboard, MMTEB
(Multilingual, v2) Retrieval likewise, or from the MMTEB paper
(arXiv 2502.13595) where the leaderboard shows no average.
"""

from dataclasses import dataclass
from typing import Literal

Task = Literal["embedding"]

SCORES = {
    "en": "Retrieval, English (MTEB eng v2)",
    "de": "Retrieval, German (MTEB deu v1)",
    "multilingual": "Retrieval, multilingual (MMTEB v2)",
}
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
    task: Task = "embedding"
    # For choosing a model (shown in paperus' administration).
    description: str = ""
    licence: str = ""
    download_mb: int = 0
    scores: tuple[tuple[str, float], ...] = ()
    """Published retrieval scores (nDCG@10, out of 100) by benchmark, see SCORES."""

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
            description=(
                "Multilingual, long inputs; strong but slow on a CPU (full precision)."
            ),
            licence="MIT",
            download_mb=2270,
            scores=(("multilingual", 54.6),),
        ),
        # The same model in int8 (570 MB): several times faster on a CPU,
        # nearly the same quality; vectors differ, so it counts as its own.
        ModelSpec(
            name="bge-m3-int8",
            repo="Xenova/bge-m3",
            revision="4de13258303883538bd53b696b452bf8099f0858",
            onnx_file="onnx/model_int8.onnx",
            tokenizer_file="tokenizer.json",
            pooling="cls",
            dimensions=1024,
            max_tokens=8192,
            description=(
                "bge-m3 in int8: faster and a quarter of the size, nearly the same "
                "quality."
            ),
            licence="MIT",
            download_mb=570,
            scores=(("multilingual", 54.6),),
        ),
        # Snowflake Arctic Embed v2 (Apache-2.0): multilingual, made for
        # retrieval, long inputs; int8.
        ModelSpec(
            name="arctic-embed-m-v2",
            repo="Snowflake/snowflake-arctic-embed-m-v2.0",
            revision="95c2741480856aa9666782eb4afe11959938017f",
            onnx_file="onnx/model_quantized.onnx",
            tokenizer_file="tokenizer.json",
            pooling="cls",
            dimensions=768,
            max_tokens=8192,
            query_prefix="query: ",
            description=(
                "Recommended: multilingual and made for search; good quality, fast, "
                "small."
            ),
            licence="Apache-2.0",
            download_mb=311,
            scores=(
                ("en", 58.4),
                ("de", 55.2),
                ("multilingual", 54.8),
            ),
        ),
        ModelSpec(
            name="arctic-embed-l-v2",
            repo="Snowflake/snowflake-arctic-embed-l-v2.0",
            revision="ac6544c8a46e00af67e330e85a9028c66b8cfd9a",
            onnx_file="onnx/model_quantized.onnx",
            tokenizer_file="tokenizer.json",
            pooling="cls",
            dimensions=1024,
            max_tokens=8192,
            query_prefix="query: ",
            description=(
                "The best quality here, multilingual; about half as fast as the medium "
                "one."
            ),
            licence="Apache-2.0",
            download_mb=570,
            scores=(
                ("en", 58.6),
                ("de", 57.1),
                ("multilingual", 58.4),
            ),
        ),
        # Alibaba GTE multilingual (Apache-2.0): long inputs, int8.
        ModelSpec(
            name="gte-multilingual-base",
            repo="onnx-community/gte-multilingual-base",
            revision="2edbf5e672aab465f9ed4c154a8b61791c082c69",
            onnx_file="onnx/model_quantized.onnx",
            tokenizer_file="tokenizer.json",
            pooling="cls",
            dimensions=768,
            max_tokens=8192,
            description="Multilingual, long inputs, fast.",
            licence="Apache-2.0",
            download_mb=340,
            scores=(("en", 50.9),),
        ),
        # E5 (MIT), int8: base and large; inputs up to 512 tokens.
        ModelSpec(
            name="multilingual-e5-base",
            repo="Xenova/multilingual-e5-base",
            revision="1ec9243030a27d1a115d5c340572074c125b58b2",
            onnx_file="onnx/model_quantized.onnx",
            tokenizer_file="tokenizer.json",
            pooling="mean",
            dimensions=768,
            max_tokens=512,
            query_prefix="query: ",
            passage_prefix="passage: ",
            description="Multilingual, fast; inputs up to 512 tokens.",
            licence="MIT",
            download_mb=279,
            scores=(
                ("en", 49.0),
                ("de", 48.8),
                ("multilingual", 52.7),
            ),
        ),
        ModelSpec(
            name="multilingual-e5-large",
            repo="Xenova/multilingual-e5-large",
            revision="00fc3aeb3dbb95842de2ac1961d33c6319acf57b",
            onnx_file="onnx/model_quantized.onnx",
            tokenizer_file="tokenizer.json",
            pooling="mean",
            dimensions=1024,
            max_tokens=512,
            query_prefix="query: ",
            passage_prefix="passage: ",
            description="Multilingual; inputs up to 512 tokens; slow.",
            licence="MIT",
            download_mb=562,
            scores=(
                ("en", 51.5),
                ("de", 50.0),
                ("multilingual", 54.1),
            ),
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
            description="Small and very fast, for weak machines; lower quality.",
            licence="MIT",
            download_mb=118,
            scores=(
                ("en", 46.4),
                ("de", 48.2),
                ("multilingual", 49.3),
            ),
        ),
    ]
}
