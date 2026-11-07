from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from paperus_ml.config import Settings
from paperus_ml.encoder import Encoder
from paperus_ml.main import create_app
from paperus_ml.manager import ModelManager
from paperus_ml.models import MODELS
from paperus_ml.ocr import Bounds, NotAnImage, Reader, reading_order
from tests.test_service import CountingLoader
from tests.tiny_model import write_tiny_model, write_tiny_ocr

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


# A page for the tiny OCR models: lines of black blocks, each read as "x".
Blocks = tuple[int, int, int, int]
"""Left, top, how many blocks, gray level (0 black, 255 white)."""


def page(lines: list[Blocks], tilt: float = 0.0) -> bytes:
    """A PNG; ``tilt`` turns it by that many degrees, as a scan can be."""
    image = np.full((800, 600, 3), 255, np.uint8)
    for left, top, blocks, gray in lines:
        for n in range(blocks):
            x = left + 36 * n
            cv2.rectangle(image, (x, top), (x + 24, top + 12), (gray,) * 3, -1)
    if tilt:
        turn = cv2.getRotationMatrix2D((300, 400), tilt, 1.0)
        image = cv2.warpAffine(image, turn, (600, 800), borderValue=(255, 255, 255))
    return cv2.imencode(".png", image)[1].tobytes()


TWO_COLUMNS = [
    (40, 40, 12, 0),  # the title, across both columns
    *((40, 100 + 30 * n, 4 + n % 3, 0) for n in range(5)),
    *((330, 100 + 30 * n, 6 + n % 2, 0) for n in range(5)),
    (40, 400, 6, 110),  # dark gray: still text
    (40, 450, 6, 200),  # light gray: found, but nothing read
    (40, 500, 6, 235),  # lighter still: not even found
]


@pytest.fixture
def reader(tmp_path: Path) -> Reader:
    return Reader(write_tiny_ocr(tmp_path), tmp_path, max_batch_texts=4)


@pytest.mark.parametrize("tilt", [0.0, 3.0])
def test_reader_reads_columns_one_after_the_other(reader: Reader, tilt: float) -> None:
    """Also on a scan turned a little, enough to close the gap between the
    columns."""
    read = reader.read(page(TWO_COLUMNS, tilt))
    assert (read.width, read.height) == (600, 800)
    blocks = [block.split("\n") for block in read.text.split("\n\n")]
    assert blocks == [
        ["x" * 12, *("x" * (4 + n % 3) for n in range(5))],
        ["x" * (6 + n % 2) for n in range(5)],
        ["x" * 6],
    ]
    assert [line.text for line in read.lines] == read.text.split()
    assert all(0.5 <= line.score <= 1 for line in read.lines)
    if not tilt:
        left, top, right, bottom = read.lines[0].box
        assert left < 40 < 40 + 36 * 11 + 24 < right and top < 40 < 52 < bottom


def test_reader_turns_vertical_lines(reader: Reader) -> None:
    image = np.full((400, 300, 3), 255, np.uint8)
    cv2.rectangle(image, (140, 60), (150, 340), (0, 0, 0), -1)
    read = reader.read(cv2.imencode(".png", image)[1].tobytes())
    assert read.text == "x"
    left, top, right, bottom = read.lines[0].box
    assert bottom - top > 3 * (right - left)


def test_reader_needs_an_image(reader: Reader) -> None:
    with pytest.raises(NotAnImage):
        reader.read(b"\x89PNG not really")
    assert reader.read(page([])).text == ""
