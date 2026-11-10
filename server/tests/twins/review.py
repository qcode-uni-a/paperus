"""Look over the layout twins: each drawn with fluent mode's pieces (blue a
column, purple across the page; a bar in the corner shows its place in
reading order, longer for later ones) and its lines (green: read in order,
red: not, grey: running header or footer), into ``OUT/index.html``.

Run from ``server/``::

    uv run python -m tests.twins.review OUT [--accept] [NAME ...]

``--accept``: take the order and the columns read now as the twins'
expected ones (once the drawing shows them right).
"""

import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pypdfium2

from paperus.page_layout import Piece, analyse
from tests.twins import twins
from tests.twins.check import check, middle

SCALE = 1.4


def accepted(spec: dict[str, Any], columns: bool, pieces: list[Piece]) -> None:
    """The spec with the order, columns and figures' parts read now."""
    _, piece_of = check(spec, columns, pieces)
    height = spec["size"][1]
    # Kept "headers or footers" away from the page's very edge: a figure's
    # labels, footnotes, lines of an equation the measuring took for them.
    for i, line in enumerate(spec["lines"]):
        if line["role"] != "furniture" or piece_of[i] < 0:
            continue
        if line["box"][1] < height * 0.04 or line["box"][3] > height * 0.96:
            continue
        x, y = middle(line["box"])
        in_figure = any(
            f["box"][0] - 4 <= x <= f["box"][2] + 4
            and f["box"][1] - 4 <= y <= f["box"][3] + 4
            for f in spec["figures"]
        )
        line["role"] = "figure" if in_figure else "body"
    body = sorted(
        (
            (line, piece_of[i])
            for i, line in enumerate(spec["lines"])
            if line["role"] == "body"
        ),
        key=lambda b: (
            b[1] if b[1] >= 0 else 10**9,
            middle(b[0]["box"])[1],
            middle(b[0]["box"])[0],
        ),
    )
    order = 0
    for line, piece in body:
        # Lines left out at the page's top or bottom edge: a header or a
        # footer the measuring missed.
        if piece < 0 and (
            line["box"][3] < height * 0.12 or line["box"][1] > height * 0.88
        ):
            line["role"] = "furniture"
            line.pop("order", None)
        else:
            line["order"] = order
            order += 1
    spec["columns"] = columns
    # A figure fluent mode divides: its parts, each whole in one piece.
    for figure in spec["figures"]:
        x0, y0, x1, y1 = figure["box"]
        parts = [
            [round(v, 1) for v in box]
            for box in (
                [
                    max(x0, p["x"]),
                    max(y0, p["y"]),
                    min(x1, p["x"] + p["width"]),
                    min(y1, p["y"] + p["height"]),
                ]
                for p in pieces
            )
            if box[2] > box[0]
            and box[3] > box[1]
            and (box[2] - box[0]) * (box[3] - box[1]) > (x1 - x0) * (y1 - y0) * 0.05
        ]
        # Divided, or partly left out (a cover's picture reaching into the
        # margin): what is shown, each part whole.
        shown = sum((c - a) * (d - b) for a, b, c, d in parts)
        if len(parts) > 1 or shown < (x1 - x0) * (y1 - y0) * 0.9:
            figure["parts"] = parts
        else:
            figure.pop("parts", None)


def png(image: np.ndarray) -> bytes:
    """An RGB PNG of rows of columns of 3 bytes."""
    height, width, _ = image.shape
    rows = b"".join(b"\0" + image[y].tobytes() for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )


def drawn(
    page: pypdfium2.PdfPage,
    spec: dict[str, Any],
    pieces: list[Piece],
    piece_of: list[int],
) -> bytes:
    """The twin with its lines and pieces drawn over it."""
    bitmap = page.render(scale=SCALE, rev_byteorder=True)
    image = (
        np.frombuffer(bytes(bitmap.buffer), dtype=np.uint8)
        .reshape(bitmap.height, bitmap.stride)[:, : bitmap.width * 3]
        .reshape(bitmap.height, bitmap.width, 3)
        .astype(np.float32)
    )
    bitmap.close()
    height, width, _ = image.shape

    def box(x0: float, y0: float, x1: float, y1: float) -> tuple[slice, slice]:
        a, b = max(0, int(y0 * SCALE)), min(height, int(y1 * SCALE) + 1)
        c, d = max(0, int(x0 * SCALE)), min(width, int(x1 * SCALE) + 1)
        return slice(a, b), slice(c, d)

    def tint(
        where: tuple[slice, slice], colour: tuple[int, int, int], alpha: float
    ) -> None:
        image[where] = image[where] * (1 - alpha) + np.array(colour) * alpha

    read = sorted(
        (
            (line, piece_of[i])
            for i, line in enumerate(spec["lines"])
            if line["role"] == "body" and piece_of[i] >= 0
        ),
        key=lambda b: (b[1], middle(b[0]["box"])[1], middle(b[0]["box"])[0]),
    )
    in_order: dict[int, bool] = {}
    highest = -1
    for line, _ in read:
        in_order[line["order"]] = line["order"] > highest
        highest = max(highest, line["order"])
    for i, line in enumerate(spec["lines"]):
        kept = piece_of[i] >= 0
        if line["role"] == "figure":
            continue
        if line["role"] == "furniture":
            colour = (220, 0, 0) if kept else (120, 120, 120)
        elif not kept or not in_order.get(line["order"]):
            colour = (220, 0, 0)
        else:
            colour = (0, 160, 60)
        tint(box(*line["box"]), colour, 0.35)
    for n, p in enumerate(pieces):
        colour = (122, 60, 255) if p["wide"] else (0, 96, 223)
        x0, y0 = p["x"], p["y"]
        x1, y1 = x0 + p["width"], y0 + p["height"]
        for edge in (
            (x0, y0, x1, y0 + 1),
            (x0, y1 - 1, x1, y1),
            (x0, y0, x0 + 1, y1),
            (x1 - 1, y0, x1, y1),
        ):
            tint(box(*edge), colour, 1)
        tint(box(x0, y0, x0 + 4 + 4 * n, y0 + 6), colour, 1)
    return png(image.clip(0, 255).astype(np.uint8))


def main() -> None:
    out = Path(sys.argv[1])
    accept = "--accept" in sys.argv[2:]
    wanted = {name for name in sys.argv[2:] if name != "--accept"}
    out.mkdir(parents=True, exist_ok=True)
    cards = []
    for path in sorted(twins.PAGES.glob("*.json")):
        spec = json.loads(path.read_text())
        if wanted and spec["name"] not in wanted:
            continue
        pdf = out / f"{spec['name']}.pdf"
        pdf.write_bytes(twins.pdf(spec))
        with pypdfium2.PdfDocument(pdf) as document:
            page = document[0]
            layout = analyse(page, spec["first"])
            columns, pieces = layout["columns"], layout["pieces"]
            if accept and not spec.get("todo"):
                accepted(spec, columns, pieces)
                path.write_text(json.dumps(spec, indent=1) + "\n")
            problems, piece_of = check(spec, columns, pieces)
            (out / f"{spec['name']}.png").write_bytes(
                drawn(page, spec, pieces, piece_of)
            )
        verdict = "<br>".join(problems) if problems else "All right"
        cards.append(
            f"<section><h2>{spec['name']}</h2><p>{spec['source']}</p>"
            f"<p class={'bad' if problems else 'good'}>{verdict}</p>"
            f"<img src='{spec['name']}.png' "
            f"width='{round(spec['size'][0] * SCALE / 2)}'>"
            "</section>"
        )
    (out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Layout twins</title><style>"
        "body{font:14px system-ui;margin:24px;background:#f4f5f7}"
        "section{display:inline-block;vertical-align:top;margin:0 16px 24px 0;"
        "background:white;padding:12px;border-radius:8px;max-width:440px}"
        "h2{font-size:15px;margin:0}.bad{color:#b00020}.good{color:#0a7a3a}"
        "img{border:1px solid #ddd}</style>" + "".join(cards)
    )
    print(f"{len(cards)} twins: {out / 'index.html'}")


if __name__ == "__main__":
    main()
