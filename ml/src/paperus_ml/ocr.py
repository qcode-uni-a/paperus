"""Reading text in images (OCR) with PaddleOCR's models in ONNX Runtime:
one model finds the text lines on a page, another reads each line. For
scanned PDFs (no text layer) and photos of notes.

The steps follow PaddleOCR's and RapidOCR's (both Apache-2.0); the reading
order is our own: columns are read one after the other, as in a paper.
"""

import math
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt
import yaml

from paperus_ml import metrics
from paperus_ml.device import Device, run_options
from paperus_ml.encoder import open_session
from paperus_ml.models import ModelSpec

# OpenCV's arrays (8-bit images, float corners), loosely typed as OpenCV's are.
Image = npt.NDArray[Any]
Box = npt.NDArray[Any]
Bounds = tuple[int, int, int, int]
"""Left, top, right, bottom in pixels of the image."""

# Finding lines: the page scaled so its shorter side has at least this many
# pixels and its longer side at most that many (multiples of 32).
DET_MIN_SIDE = 736
DET_MAX_SIDE = 2000
# PaddleOCR's settings for its PP-OCRv6 detection models.
DET_THRESH = 0.2
BOX_THRESH = 0.45
UNCLIP_RATIO = 1.4
MAX_LINES = 3000
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
# Reading lines: 48 pixels high, at least 320 wide.
LINE_HEIGHT = 48
MIN_LINE_WIDTH = 320
# Lines read with less confidence are left out (mostly not text at all).
MIN_SCORE = 0.5


class NotAnImage(ValueError):
    pass


@dataclass
class Line:
    text: str
    score: float
    box: Bounds


@dataclass
class Page:
    text: str
    """The lines in reading order; a blank line between blocks."""
    lines: list[Line]
    width: int
    height: int


def characters(model_dir: Path, spec: ModelSpec) -> list[str]:
    """What the line model can write: its list from PaddleOCR's settings,
    after CTC's blank, and the space last."""
    config = yaml.safe_load((model_dir / spec.tokenizer_file).read_text())
    return ["", *config["PostProcess"]["character_dict"], " "]


class Reader:
    def __init__(
        self,
        spec: ModelSpec,
        model_dir: Path,
        *,
        intra_op_threads: int = 0,
        max_batch_texts: int = 32,
        max_batch_tokens: int = 16384,
        device: Device = "cpu",
    ) -> None:
        assert spec.detector is not None
        self.spec = spec
        self.max_batch_lines = max_batch_texts
        self.detector, _ = open_session(
            model_dir / spec.detector.folder / spec.detector.onnx_file,
            intra_op_threads,
            device,
        )
        self.recognizer, self.device = open_session(
            model_dir / spec.onnx_file, intra_op_threads, device
        )
        self.run_options = run_options(self.device)
        self.characters = characters(model_dir, spec)
        # One page at a time, as for the other models (see Encoder).
        self.running = threading.RLock()

    def read(self, data: bytes) -> Page:
        """The text in an image (PNG, JPEG, TIFF, WebP, …)."""
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise NotAnImage("not an image this service can read")
        height, width = image.shape[:2]
        with self.running:
            started = time.perf_counter()
            boxes = self._find_lines(image)
            crops = [_crop(image, box) for box in boxes]
            read = self._read_lines(crops)
            metrics.BATCH_SECONDS.labels(self.spec.name).observe(
                time.perf_counter() - started
            )
        kept = [
            (box, Line(text=text.strip(), score=score, box=_bounds(box)))
            for box, (text, score) in zip(boxes, read, strict=True)
            if score >= MIN_SCORE and text.strip()
        ]
        # In order by their positions on the page straightened: a scan is
        # often tilted a little, enough to close the gap between columns.
        straight = _straightened([box for box, _ in kept], (width / 2, height / 2))
        order = reading_order([_bounds(box) for box in straight], width)
        blocks = [[kept[index][1] for index in block] for block in order]
        text = "\n\n".join("\n".join(line.text for line in block) for block in blocks)
        return Page(
            text=text,
            lines=[line for block in blocks for line in block],
            width=width,
            height=height,
        )

    def _find_lines(self, image: Image) -> list[Box]:
        """Quadrilaterals around the text lines (4 corners each)."""
        height, width = image.shape[:2]
        scale = max(1.0, DET_MIN_SIDE / min(height, width))
        scale = min(scale, DET_MAX_SIDE / max(height, width))
        new_h = max(32, round(height * scale / 32) * 32)
        new_w = max(32, round(width * scale / 32) * 32)
        resized = cv2.resize(image, (new_w, new_h)).astype(np.float32) / 255
        tensor = ((resized - MEAN) / STD).transpose(2, 0, 1)[None]
        output = self.detector.run(
            None, {"x": tensor.astype(np.float32)}, self.run_options
        )[0]
        probabilities = np.asarray(output, dtype=np.float32)[0, 0]
        boxes = _boxes(probabilities, width / new_w, height / new_h)
        return [b for b in boxes if np.ptp(b[:, 0]) > 3 and np.ptp(b[:, 1]) > 3]

    def _read_lines(self, crops: Sequence[Image]) -> list[tuple[str, float]]:
        """Each line's text and confidence; by width, so little is padded."""
        result: list[tuple[str, float]] = [("", 0.0)] * len(crops)
        ratios = [c.shape[1] / max(1, c.shape[0]) for c in crops]
        order = sorted(range(len(crops)), key=lambda i: ratios[i])
        for start in range(0, len(order), self.max_batch_lines):
            group = order[start : start + self.max_batch_lines]
            ratio = max([MIN_LINE_WIDTH / LINE_HEIGHT, *(ratios[i] for i in group)])
            batch_width = math.ceil(LINE_HEIGHT * ratio)
            batch = np.zeros((len(group), 3, LINE_HEIGHT, batch_width), np.float32)
            for row, index in enumerate(group):
                width = min(batch_width, math.ceil(LINE_HEIGHT * ratios[index]))
                line = cv2.resize(crops[index], (width, LINE_HEIGHT))
                line = (line.astype(np.float32) / 255 - 0.5) / 0.5
                batch[row, :, :, :width] = line.transpose(2, 0, 1)
            output = self.recognizer.run(None, {"x": batch}, self.run_options)[0]
            steps = np.asarray(output, dtype=np.float32)
            for row, index in enumerate(group):
                result[index] = self._decode(steps[row])
        return result

    def _decode(self, steps: npt.NDArray[np.float32]) -> tuple[str, float]:
        """CTC: the likeliest character per step, repeats and blanks dropped."""
        best = steps.argmax(axis=1)
        confidence = steps.max(axis=1)
        keep = best != 0
        keep[1:] &= best[1:] != best[:-1]
        if not keep.any():
            return "", 0.0
        text = "".join(self.characters[i] for i in best[keep])
        return text, float(confidence[keep].mean())


def _boxes(
    probabilities: npt.NDArray[np.float32], scale_x: float, scale_y: float
) -> list[Box]:
    """Text regions of the probability map, grown back to the whole line
    (DB's "unclip") and scaled to the original image."""
    mask = (probabilities > DET_THRESH).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours[:MAX_LINES]:
        (cx, cy), (w, h), angle = cv2.minAreaRect(contour)
        if min(w, h) < 3 or _region_score(probabilities, contour) < BOX_THRESH:
            continue
        # Growing a rectangle by d = area * ratio / perimeter on each side
        # (at least 1 pixel, as both sides are at least 3).
        grow = w * h * UNCLIP_RATIO / (2 * (w + h))
        corners = cv2.boxPoints(((cx, cy), (w + 2 * grow, h + 2 * grow), angle))
        corners[:, 0] = np.clip(corners[:, 0] * scale_x, 0, None)
        corners[:, 1] = np.clip(corners[:, 1] * scale_y, 0, None)
        boxes.append(_clockwise(corners))
    return boxes


def _region_score(
    probabilities: npt.NDArray[np.float32], contour: npt.NDArray[Any]
) -> float:
    """The mean probability inside the region."""
    x, y, w, h = cv2.boundingRect(contour)
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [contour - [x, y]], 1)
    return float(cv2.mean(probabilities[y : y + h, x : x + w], mask)[0])


def _clockwise(corners: Box) -> Box:
    """Top left, top right, bottom right, bottom left."""
    by_x = corners[np.argsort(corners[:, 0])]
    left, right = by_x[:2], by_x[2:]
    top_left, bottom_left = left[np.argsort(left[:, 1])]
    top_right, bottom_right = right[np.argsort(right[:, 1])]
    return np.array([top_left, top_right, bottom_right, bottom_left], np.float32)


def _crop(image: Image, box: Box) -> Image:
    """The line, straightened; vertical lines turned to read left to right."""
    width = int(max(np.linalg.norm(box[0] - box[1]), np.linalg.norm(box[2] - box[3])))
    height = int(max(np.linalg.norm(box[0] - box[3]), np.linalg.norm(box[1] - box[2])))
    target = np.array(
        [[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(box, target)
    crop = cv2.warpPerspective(
        image,
        matrix,
        (max(1, width), max(1, height)),
        borderMode=cv2.BORDER_REPLICATE,
        flags=cv2.INTER_CUBIC,
    )
    if height >= 1.5 * width:
        crop = np.rot90(crop)
    return np.ascontiguousarray(crop)


def _bounds(box: Box) -> Bounds:
    return (
        int(box[:, 0].min()),
        int(box[:, 1].min()),
        int(box[:, 0].max()),
        int(box[:, 1].max()),
    )


def _straightened(boxes: list[Box], center: tuple[float, float]) -> list[Box]:
    """The boxes turned back by the page's tilt: the median slope of the
    long lines (within 10 degrees; more is not a slightly tilted scan)."""
    slopes = [
        math.atan2(box[1][1] - box[0][1], box[1][0] - box[0][0])
        for box in boxes
        if np.linalg.norm(box[1] - box[0]) > 3 * np.linalg.norm(box[3] - box[0])
    ]
    tilt = float(np.median(slopes)) if slopes else 0.0
    if abs(tilt) < 1e-3 or abs(tilt) > math.radians(10):
        return boxes
    turn = cv2.getRotationMatrix2D(center, math.degrees(tilt), 1.0)
    return [cv2.transform(box[None], turn)[0] for box in boxes]


def reading_order(boxes: list[Bounds], page_width: int) -> list[list[int]]:
    """The lines (their boxes: left, top, right, bottom) in blocks, in the
    order one reads them, as indices: split the page where a gap runs
    through it, from top to bottom between columns (preferred) or across,
    and so on within each part (a recursive XY cut). Columns are read one
    after the other, not line by line across."""
    column_gap = max(8, page_width * 0.015)

    def gaps(items: list[int], axis: int, minimum: float) -> list[tuple[float, float]]:
        """(width, position) of each gap no line crosses."""
        spans = sorted((boxes[i][axis], boxes[i][axis + 2]) for i in items)
        found = []
        end = spans[0][1]
        for start, stop in spans[1:]:
            if start - end >= minimum:
                found.append((start - end, (start + end) / 2))
            end = max(end, stop)
        return found

    def split(items: list[int]) -> list[list[int]]:
        if len(items) < 2:
            return [items]
        for axis, minimum in ((0, column_gap), (1, 1.0)):
            found = gaps(items, axis, minimum)
            if found:
                _, at = max(found)
                first = [i for i in items if boxes[i][axis + 2] <= at]
                rest = [i for i in items if boxes[i][axis + 2] > at]
                return split(first) + split(rest)
        return [sorted(items, key=lambda i: (boxes[i][1], boxes[i][0]))]

    if not boxes:
        return []
    blocks = split(list(range(len(boxes))))
    # Neighbouring pieces of one paragraph (cut at a line gap) join again.
    merged: list[list[int]] = [blocks[0]]
    for block in blocks[1:]:
        last = boxes[merged[-1][-1]]
        first = boxes[block[0]]
        line_height = max(1, last[3] - last[1])
        same_column = abs(first[0] - last[0]) < line_height * 2
        close = 0 <= first[1] - last[3] < line_height
        if same_column and close:
            merged[-1].extend(block)
        else:
            merged.append(block)
    return merged
