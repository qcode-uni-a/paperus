from pathlib import Path

from fastapi.testclient import TestClient

from paperus_ml.config import Settings
from paperus_ml.encoder import Encoder
from paperus_ml.main import create_app
from paperus_ml.manager import ModelManager
from paperus_ml.models import MODELS
from paperus_ml.ocr import Bounds, reading_order
from tests.test_service import CountingLoader
from tests.tiny_model import write_tiny_model

Line = tuple[str, Bounds]


def line(text: str, left: int, top: int, right: int, height: int = 20) -> Line:
    return text, (left, top, right, top + height)


def texts(lines: list[Line], page_width: int = 1654) -> list[list[str]]:
    blocks = reading_order([box for _, box in lines], page_width)
    return [[lines[index][0] for index in block] for block in blocks]


def test_columns_are_read_one_after_the_other() -> None:
    title = line("Title across the page", 100, 50, 1500, 40)
    left = [line(f"left {n}", 100, 150 + 30 * n, 780) for n in range(4)]
    right = [line(f"right {n}", 860, 150 + 30 * n, 1540) for n in range(4)]
    # As found on the page: across, line by line.
    found = [title, *(x for pair in zip(left, right, strict=True) for x in pair)]
    assert texts(found) == [
        ["Title across the page"],
        ["left 0", "left 1", "left 2", "left 3"],
        ["right 0", "right 1", "right 2", "right 3"],
    ]


def test_paragraphs_are_blocks() -> None:
    lines = [
        line("first paragraph", 100, 100, 1500),
        line("goes on", 100, 125, 900),
        line("second paragraph", 100, 200, 1500),
    ]
    assert texts(lines) == [["first paragraph", "goes on"], ["second paragraph"]]
    assert reading_order([], 1654) == []


def test_ocr_needs_an_ocr_model_and_an_image(tmp_path: Path) -> None:
    tiny = Encoder(write_tiny_model(tmp_path), tmp_path)
    manager = ModelManager(Settings(), CountingLoader(tiny))
    with TestClient(create_app(Settings(), manager)) as client:
        assert client.post("/ocr/bge-m3", content=b"\x89PNG").status_code == 422
        assert client.post("/ocr/pp-ocrv6-small", content=b"").status_code == 422
        assert client.post("/ocr/nope", content=b"x").status_code == 404
        listed = {m["name"]: m for m in client.get("/models").json()}
        assert listed["pp-ocrv6-small"]["task"] == "ocr"
    assert MODELS["pp-ocrv6-small"].detector is not None
