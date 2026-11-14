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

Task = Literal["embedding", "rerank", "ocr"]

SCORES = {
    "en": "Retrieval, English (MTEB eng v2)",
    "de": "Retrieval, German (MTEB deu v1)",
    "multilingual": "Retrieval, multilingual (MMTEB v2)",
}
Pooling = Literal["cls", "mean", "last", "output"]
"""How token vectors become a text's vector: the first token's, their mean,
the last token's (decoder models: Qwen3-Embedding), or the model's own
``sentence_embedding`` output (EmbeddingGemma: its pooling and dense layers
are in the ONNX file)."""
Kind = Literal["query", "passage"]
Layout = Literal["onnx", "qwen3-vl"]
"""How a model's files are laid out: one ONNX file and its tokenizer, or
Qwen3-VL's (``paperus_ml.qwen3_vl``): a vision encoder, token table and
tokenizer shared in ``shared/``, the task's decoder in a folder of its own."""


@dataclass(frozen=True)
class Part:
    """A second model a model needs, from its own repository (OCR: the one
    that finds the text lines), downloaded into a folder of its own."""

    repo: str
    revision: str
    onnx_file: str
    folder: str


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
    gpu_onnx_file: str | None = None
    """On a GPU: the fp16 (or full-precision) export, as int8 runs slowly
    there; vectors differ from the int8 ones only by rounding."""
    query_prefix: str = ""
    passage_prefix: str = ""
    task: Task = "embedding"
    detector: Part | None = None
    # For choosing a model (shown in paperus' administration).
    description: str = ""
    licence: str = ""
    download_mb: int = 0
    scores: tuple[tuple[str, float], ...] = ()
    """Published retrieval scores (nDCG@10, out of 100) by benchmark, see SCORES."""
    parameters: int = 0
    """Its size: how many weights (0: not published)."""
    released: str = ""
    """When it was published ("2024-01"), from its first version on Hugging
    Face."""
    recommended: tuple[str, ...] = ()
    """Where it is the one to use for its task ("cpu", "cuda"), from our
    question set (docs/search.md)."""
    layout: Layout = "onnx"
    images: bool = False
    """Takes images (figures) too, in the same space as texts (embedding) or
    as candidates (reranking)."""

    def onnx_file_for(self, device: str) -> str:
        return (
            (self.gpu_onnx_file or self.onnx_file)
            if device == "cuda"
            else self.onnx_file
        )

    def vectors(self, device: str) -> str:
        """What the vectors are stored as in paperus: the model's name for
        its usual file, with the variant for another one (``…@fp16``), as
        vectors of different files must not be mixed."""
        file = self.onnx_file_for(device)
        if file == self.onnx_file:
            return self.name
        if "fp16" in file:
            return f"{self.name}@fp16"
        if "int8" in file or "quant" in file:
            return f"{self.name}@int8"
        return f"{self.name}@fp32"

    def prefix(self, kind: Kind) -> str:
        return self.query_prefix if kind == "query" else self.passage_prefix


MODELS = {
    spec.name: spec
    for spec in [
        # Multilingual, 1024 dimensions, long inputs; ONNX from the authors.
        ModelSpec(
            name="bge-m3",
            parameters=568_000_000,
            released="2024-01",
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
            parameters=568_000_000,
            released="2024-01",
            repo="Xenova/bge-m3",
            revision="4de13258303883538bd53b696b452bf8099f0858",
            onnx_file="onnx/model_int8.onnx",
            gpu_onnx_file="onnx/model_fp16.onnx",
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
            parameters=305_000_000,
            released="2024-11",
            repo="Snowflake/snowflake-arctic-embed-m-v2.0",
            revision="95c2741480856aa9666782eb4afe11959938017f",
            onnx_file="onnx/model_quantized.onnx",
            gpu_onnx_file="onnx/model_fp16.onnx",
            tokenizer_file="tokenizer.json",
            pooling="cls",
            dimensions=768,
            max_tokens=8192,
            query_prefix="query: ",
            description=(
                "Multilingual and made for search; the best on our questions, fast, "
                "small. Good without a reranker too."
            ),
            recommended=("cpu", "cuda"),
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
            parameters=568_000_000,
            released="2024-11",
            repo="Snowflake/snowflake-arctic-embed-l-v2.0",
            revision="ac6544c8a46e00af67e330e85a9028c66b8cfd9a",
            onnx_file="onnx/model_quantized.onnx",
            gpu_onnx_file="onnx/model_fp16.onnx",
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
            parameters=305_000_000,
            released="2024-07",
            repo="onnx-community/gte-multilingual-base",
            revision="2edbf5e672aab465f9ed4c154a8b61791c082c69",
            onnx_file="onnx/model_quantized.onnx",
            gpu_onnx_file="onnx/model_fp16.onnx",
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
            parameters=278_000_000,
            released="2023-05",
            repo="Xenova/multilingual-e5-base",
            revision="1ec9243030a27d1a115d5c340572074c125b58b2",
            onnx_file="onnx/model_quantized.onnx",
            gpu_onnx_file="onnx/model_fp16.onnx",
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
            parameters=560_000_000,
            released="2023-06",
            repo="Xenova/multilingual-e5-large",
            revision="00fc3aeb3dbb95842de2ac1961d33c6319acf57b",
            onnx_file="onnx/model_quantized.onnx",
            gpu_onnx_file="onnx/model_fp16.onnx",
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
        # Qwen3-Embedding 0.6B (Apache-2.0): a decoder (last token's vector),
        # queries with an instruction; many languages, long texts. On our
        # questions as good as arctic-embed-m-v2 with a reranker, worse
        # without (docs/search.md).
        ModelSpec(
            name="qwen3-embedding-0.6b",
            parameters=596_000_000,
            released="2025-06",
            repo="onnx-community/Qwen3-Embedding-0.6B-ONNX",
            revision="c25a394dd583836952667c12f008335071b3f43d",
            onnx_file="onnx/model_quantized.onnx",
            gpu_onnx_file="onnx/model_fp16.onnx",
            tokenizer_file="tokenizer.json",
            pooling="last",
            dimensions=1024,
            max_tokens=1024,
            query_prefix=(
                "Instruct: Given a web search query, retrieve relevant passages"
                " that answer the query\nQuery:"
            ),
            description=(
                "Qwen3-Embedding 0.6B: many languages, long texts; slow on a CPU."
            ),
            licence="Apache-2.0",
            download_mb=620,
        ),
        # EmbeddingGemma 2 (Apache-2.0): text, images, video and sound in
        # one space; here its text model (the others' features empty), its
        # pooling in the ONNX file. On our questions worse than
        # arctic-embed-m-v2 without a reranker (docs/search.md).
        ModelSpec(
            name="embeddinggemma-2",
            parameters=744_000_000,
            released="2026-09",
            repo="onnx-community/embeddinggemma-2-ONNX",
            revision="daa72c51243991dfcaf9f9137d2c573d8f7790c0",
            onnx_file="onnx/model_quantized.onnx",
            gpu_onnx_file="onnx/model_fp16.onnx",
            tokenizer_file="tokenizer.json",
            pooling="output",
            dimensions=768,
            max_tokens=1024,
            query_prefix="task: search result | query: ",
            passage_prefix="title: none | text: ",
            description=(
                "EmbeddingGemma 2: many languages; slower than the recommended "
                "one on a CPU."
            ),
            licence="Apache-2.0",
            download_mb=330,
        ),
        # Small and fast (int8, 118 MB); for development and small machines.
        ModelSpec(
            name="multilingual-e5-small",
            parameters=118_000_000,
            released="2023-06",
            repo="Xenova/multilingual-e5-small",
            revision="761b726dd34fb83930e26aab4e9ac3899aa1fa78",
            onnx_file="onnx/model_quantized.onnx",
            gpu_onnx_file="onnx/model_fp16.onnx",
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
        # OCR: PaddleOCR's PP-OCRv6 (small), one model finding the lines and
        # one reading them; many languages in Latin script and Chinese,
        # formulas only roughly. Tested on pages of our papers and German
        # ones, clean and as scans (docs/search.md): 96-100 % of words right.
        ModelSpec(
            name="pp-ocrv6-small",
            repo="PaddlePaddle/PP-OCRv6_small_rec_onnx",
            revision="b8f84f0b80c529de40b4fbb3544b84fa7233a513",
            onnx_file="inference.onnx",
            tokenizer_file="inference.yml",
            detector=Part(
                repo="PaddlePaddle/PP-OCRv6_small_det_onnx",
                revision="28fe5895c24fd108c19eb3e8479f4ab385fbfc62",
                onnx_file="inference.onnx",
                folder="det",
            ),
            task="ocr",
            pooling="cls",
            dimensions=0,
            max_tokens=0,
            description=(
                "Reads scanned pages and photos (OCR); English, German and many "
                "other languages. About 3 s per page on a CPU."
            ),
            licence="Apache-2.0",
            download_mb=31,
            recommended=("cpu", "cuda"),
        ),
        # Rerankers: read a query and a passage together and score how well
        # they fit; for reordering the best search hits. Tested on our own
        # question set (docs/search.md): bge-reranker-v2-m3 best, MiniLM
        # English only.
        ModelSpec(
            name="bge-reranker-v2-m3",
            parameters=568_000_000,
            released="2024-03",
            repo="onnx-community/bge-reranker-v2-m3-ONNX",
            revision="6f5ff65298512715a1e669753bc754d2bc8f367b",
            onnx_file="onnx/model_int8.onnx",
            gpu_onnx_file="onnx/model_fp16.onnx",
            tokenizer_file="tokenizer.json",
            task="rerank",
            pooling="cls",
            dimensions=1,
            max_tokens=512,
            description=(
                "Multilingual reranker, the best on our questions; half a second "
                "per search on a GPU, many seconds on a CPU."
            ),
            licence="Apache-2.0",
            download_mb=571,
            # Not on a CPU: too slow there, and the recommended embedding
            # model gains little from it (docs/search.md).
            recommended=("cuda",),
        ),
        ModelSpec(
            name="gte-multilingual-reranker-base",
            parameters=306_000_000,
            released="2024-07",
            repo="onnx-community/gte-multilingual-reranker-base",
            revision="ee64367e35a2db0da46bb6497e13a18f8bd585cb",
            onnx_file="onnx/model_int8.onnx",
            gpu_onnx_file="onnx/model_fp16.onnx",
            tokenizer_file="tokenizer.json",
            task="rerank",
            pooling="cls",
            dimensions=1,
            max_tokens=512,
            description=(
                "Multilingual reranker, about twice as fast as bge-reranker-v2-m3."
            ),
            licence="Apache-2.0",
            download_mb=341,
        ),
        ModelSpec(
            name="ms-marco-minilm-l6",
            parameters=22_700_000,
            released="2021-04",
            repo="cross-encoder/ms-marco-MiniLM-L-6-v2",
            revision="233902d25c440f23af6f7d6e94d2946bac0bee0a",
            onnx_file="onnx/model_quint8_avx2.onnx",
            gpu_onnx_file="onnx/model.onnx",
            tokenizer_file="tokenizer.json",
            task="rerank",
            pooling="cls",
            dimensions=1,
            max_tokens=512,
            description="Small English reranker; fast enough for a CPU.",
            licence="Apache-2.0",
            download_mb=23,
        ),
    ]
}


def recommended(device: str) -> list[ModelSpec]:
    """The models to use on ``device`` ("cpu", "cuda"), one per task (on a
    CPU no reranker)."""
    return [spec for spec in MODELS.values() if device in spec.recommended]
