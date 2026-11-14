"""Qwen3-VL in ONNX (paperus_ml.qwen3_vl): images prepared as the vision
encoder takes them, positions, sequences and batching, and the API taking
figures. The arithmetic was checked against transformers on real figures
(sizes in 5,000 of 5,000 cases, patches and positions exactly); here with
values worked out by hand and the tiny pair (tests/tiny_model.py)."""

import base64
import gc
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from paperus_ml import qwen3_vl as q
from paperus_ml.config import Settings
from paperus_ml.device import Device
from paperus_ml.encoder import Encoder
from paperus_ml.main import create_app
from paperus_ml.manager import Model, ModelManager
from paperus_ml.models import MODELS, ModelSpec
from paperus_ml.rerank import Reranker
from tests.tiny_model import (
    VL_DIMENSIONS,
    write_tiny_model,
    write_tiny_qwen3_vl,
    write_tiny_reranker,
)


def test_sizes_keep_the_shape_in_multiples_of_32() -> None:
    assert q.smart_resize(100, 100) == (96, 96)
    assert q.smart_resize(500, 1000) == (512, 992)
    # Small images grow to at least MIN_PIXELS, large ones shrink below MAX.
    assert q.smart_resize(10, 10) == (64, 64)
    h, w = q.smart_resize(4000, 3000)
    assert h * w <= q.MAX_PIXELS and h % 32 == w % 32 == 0 and h > w
    with pytest.raises(ValueError, match="200 times"):
        q.smart_resize(10, 3000)


def test_patches_in_blocks_of_two_by_two() -> None:
    # A 64 x 64 image (the smallest kept as it is): 4 x 4 patches of 16 px;
    # patch (row, column) filled with 10 * row + column (red), the rest 0.
    rgb = np.zeros((64, 64, 3), np.uint8)
    for row in range(4):
        for col in range(4):
            block = rgb[row * 16 : (row + 1) * 16, col * 16 : (col + 1) * 16]
            block[:, :, 0] = 10 * row + col
    image = q.prepare(rgb)
    assert image.grid == (4, 4) and image.tokens == 4
    assert image.pixels.shape == (16, 3 * 2 * 16 * 16)
    # Blocks of 2 x 2 patches, row by row inside a block.
    red = image.pixels[:, : 2 * 16 * 16].astype(np.float32)
    values = np.round((red[:, 0] + 1) / 2 * 255)
    assert values.tolist() == [
        0,
        1,
        10,
        11,
        2,
        3,
        12,
        13,
        20,
        21,
        30,
        31,
        22,
        23,
        32,
        33,
    ]
    # Both frames the same, other channels -1 (black).
    assert np.array_equal(red[:, :256], red[:, 256:])
    assert np.all(image.pixels[:, 2 * 256 :] == -1)


def test_images_are_resized_both_ways() -> None:
    assert q.prepare(np.zeros((100, 120, 3), np.uint8)).grid == (6, 8)  # 96 x 128
    assert q.prepare(np.zeros((20, 20, 3), np.uint8)).grid == (4, 4)  # grown


def test_grid_inputs() -> None:
    image = q.prepare(np.zeros((64, 64, 3), np.uint8))
    inputs = q.grid_inputs(image)
    rows, cols = inputs["position_ids"].T
    assert rows.tolist() == [0, 0, 1, 1, 0, 0, 1, 1, 2, 2, 3, 3, 2, 2, 3, 3]
    assert cols.tolist() == [0, 1, 0, 1, 2, 3, 2, 3, 0, 1, 0, 1, 2, 3, 2, 3]
    weights = inputs["interp_weights"].astype(np.float32)
    assert np.allclose(weights.sum(axis=1), 1, atol=1e-3)
    # The grid's corners land on the learned grid's corners.
    side = q.GRID_SIDE
    first, last = 0, 15  # patches (0, 0) and (3, 3)
    assert inputs["interp_indices"][first][weights[first].argmax()] == 0
    assert inputs["interp_indices"][last][weights[last].argmax()] == side * side - 1


def test_positions_of_text_and_an_image() -> None:
    found = q.positions([2, (4, 6), 1])
    # Text 0, 1; the image's 2 x 3 tokens: time 2, rows 2-3, columns 2-4;
    # then text from 2 + max(2, 3) = 5.
    assert found.tolist() == [
        [0, 1, 2, 2, 2, 2, 2, 2, 5],
        [0, 1, 2, 2, 2, 3, 3, 3, 5],
        [0, 1, 2, 3, 4, 2, 3, 4, 5],
    ]


def test_batches_padded_on_the_left() -> None:
    table = np.arange(8 * 2, dtype=np.float16).reshape(8, 2)
    image = q.prepare(np.zeros((64, 64, 3), np.uint8))  # four tokens
    feature = np.full((4, 2), 9, np.float16)
    deep = np.full((3, 4, 2), 7, np.float16)
    feeds = q.batch_inputs(
        [[[1, 2, 3]], [[4], image]],
        np.vstack([table, np.zeros((q.IMAGE_PAD + 1 - 8, 2), np.float16)]),
        {id(image): (feature, deep)},
    )
    # Five tokens against three: the text two to the right.
    assert feeds["attention_mask"].tolist() == [[0, 0, 1, 1, 1], [1, 1, 1, 1, 1]]
    assert feeds["inputs_embeds"][0, :2].tolist() == [[0, 0], [0, 0]]
    assert feeds["inputs_embeds"][1].tolist() == [[8, 9], *[[9, 9]] * 4]
    assert feeds["deepstack"][:, 1, 1:].tolist() == [[[7, 7]] * 4] * 3
    assert not feeds["deepstack"][:, 0].any()
    # Text 0; the image's 2 x 2 tokens at time 1, rows and columns 1-2.
    assert feeds["position_ids"][:, 1].tolist() == [
        [0, 1, 1, 1, 1],
        [0, 1, 1, 2, 2],
        [0, 1, 2, 1, 2],
    ]
    assert feeds["position_ids"][:, 0, 2:].tolist() == [[0, 1, 2]] * 3


@pytest.fixture
def pair(tmp_path: Path) -> tuple[q.MultimodalEncoder, q.MultimodalReranker]:
    embedding, reranker = write_tiny_qwen3_vl(tmp_path)
    return q.MultimodalEncoder(embedding, tmp_path), q.MultimodalReranker(
        reranker, tmp_path
    )


def picture(value: int, size: tuple[int, int] = (64, 96)) -> q.Image:
    return q.prepare(np.full((*size, 3), value, np.uint8))


def test_texts_and_figures_in_one_space(
    pair: tuple[q.MultimodalEncoder, q.MultimodalReranker],
) -> None:
    encoder, _ = pair
    figure = picture(200)
    items = [
        q.Item(text="rain"),
        q.Item(image=figure),
        q.Item(text="rain drought", image=figure),
    ]
    vectors = encoder.embed_items(items, "passage")
    assert vectors.shape == (3, VL_DIMENSIONS)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    # Batched as alone; a caption changes a figure's vector.
    alone = np.concatenate([encoder.embed_items([i], "passage") for i in items])
    assert np.allclose(vectors, alone, atol=1e-6)
    assert not np.allclose(vectors[1], vectors[2])
    # Queries get their instruction; texts alone as the other models take them.
    assert not np.allclose(
        encoder.embed(["rain"], "query"), encoder.embed(["rain"], "passage")
    )
    assert np.allclose(encoder.embed(["rain"], "passage"), vectors[:1])


def test_reranking_texts_and_figures(
    pair: tuple[q.MultimodalEncoder, q.MultimodalReranker],
) -> None:
    _, reranker = pair
    items = [q.Item(text="rain"), q.Item(image=picture(10)), q.Item(text="pasta")]
    scores = reranker.score_items("rain", items)
    assert len(scores) == 3 and len(set(scores)) == 3
    assert reranker.score("rain", ["rain", "pasta"]) == [scores[0], scores[2]]


def test_image_files_decoded() -> None:
    bgr = np.zeros((40, 50, 3), np.uint8)
    bgr[:, :, 0] = 255  # blue in OpenCV's order
    image = q.decode(cv2.imencode(".png", bgr)[1].tobytes())
    blue = image.pixels[:, 2 * 2 * 256 :].astype(np.float32)
    assert np.allclose(blue, 1) and np.allclose(image.pixels[:, : 2 * 256], -1)
    with pytest.raises(ValueError, match="not an image"):
        q.decode(b"no image")


class PairLoader:
    def __init__(self, models: dict[str, Model]) -> None:
        self.models = models

    def __call__(self, spec: ModelSpec, device: Device = "cpu") -> Model:
        return self.models[spec.name]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    embedding, reranker = write_tiny_qwen3_vl(tmp_path)
    for spec in (embedding, reranker):
        monkeypatch.setitem(MODELS, spec.name, spec)
    (tmp_path / "text").mkdir()
    (tmp_path / "reranker").mkdir(exist_ok=True)
    loader = PairLoader(
        {
            embedding.name: q.MultimodalEncoder(embedding, tmp_path),
            reranker.name: q.MultimodalReranker(reranker, tmp_path),
            # Text only:
            "bge-m3": Encoder(write_tiny_model(tmp_path / "text"), tmp_path / "text"),
            "bge-reranker-v2-m3": Reranker(
                write_tiny_reranker(tmp_path / "text"), tmp_path / "text"
            ),
        }
    )
    with TestClient(create_app(Settings(), ModelManager(Settings(), loader))) as client:
        yield client


def png(value: int) -> str:
    image = np.full((48, 64, 3), value, np.uint8)
    return base64.b64encode(cv2.imencode(".png", image)[1].tobytes()).decode()


def test_api_takes_figures(client: TestClient) -> None:
    listed = {m["name"]: m for m in client.get("/models").json()}
    assert listed["tiny-vl-embedding"]["images"] is True
    assert listed["bge-m3"]["images"] is False

    body = {
        "model": "tiny-vl-embedding",
        "texts": ["rain"],
        "images": [{"data": png(30)}, {"data": png(30), "text": "FIG. 1. rain"}],
    }
    response = client.post("/embed", json=body)
    assert response.status_code == 200, response.text
    vectors = np.array(response.json()["embeddings"])
    assert vectors.shape == (3, VL_DIMENSIONS)
    alone = client.post(
        "/embed", json={"model": "tiny-vl-embedding", "texts": ["rain"]}
    ).json()["embeddings"]
    assert np.allclose(vectors[0], alone[0], atol=1e-6)

    ranked = client.post(
        "/rerank",
        json={
            "model": "tiny-vl-reranker",
            "query": "rain",
            "passages": ["rain"],
            "images": [{"data": png(30)}],
        },
    )
    assert ranked.status_code == 200, ranked.text
    assert len(ranked.json()["scores"]) == 2
    only_figures = client.post(
        "/rerank",
        json={
            "model": "tiny-vl-reranker",
            "query": "rain",
            "images": [{"data": png(9)}],
        },
    )
    assert len(only_figures.json()["scores"]) == 1


def test_figures_refused(client: TestClient) -> None:
    def embed(**body: object) -> int:
        return client.post(
            "/embed", json={"model": "tiny-vl-embedding", **body}
        ).status_code

    assert embed() == 422  # neither texts nor figures
    assert embed(images=[{"data": "not base64!"}]) == 422
    assert embed(images=[{"data": base64.b64encode(b"text").decode()}]) == 422
    rerank = {"model": "tiny-vl-reranker", "query": "rain"}
    assert client.post("/rerank", json=rerank).status_code == 422
    # Text models take no figures.
    figure = [{"data": png(30)}]
    text_only = client.post("/embed", json={"model": "bge-m3", "images": figure})
    assert text_only.status_code == 422
    assert "takes no images" in text_only.text
    rerank = {"model": "bge-reranker-v2-m3", "query": "rain", "images": figure}
    assert client.post("/rerank", json=rerank).status_code == 422


def test_the_pair_shares_its_vision_encoder(tmp_path: Path) -> None:
    """Both models of a pair, loaded together, use one vision encoder and
    token table (on a GPU 0.8 GB less); unloaded, it goes."""
    # A revision of its own: other tests' pairs may still be alive.
    embedding, reranker = (
        replace(spec, revision=str(tmp_path)) for spec in write_tiny_qwen3_vl(tmp_path)
    )
    encoder = q.MultimodalEncoder(embedding, tmp_path)
    ranker = q.MultimodalReranker(reranker, tmp_path)
    assert encoder.runtime.vision is ranker.runtime.vision
    assert encoder.runtime.table is ranker.runtime.table
    key = (embedding.repo, embedding.revision, "0", "cpu")
    assert key in q._shared
    del encoder, ranker
    gc.collect()
    assert key not in q._shared
