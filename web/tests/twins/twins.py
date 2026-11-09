"""Layout twins: PDFs with the layout of real papers' pages (``pages/*.json``,
measured by ``measure.py``) and none of their words or pictures, for the
tests of fluent mode (``../layout.test.ts``). Built when the tests run, not
kept: lines of filler words as wide and as large as the paper's, figures as
coloured silhouettes (cells where the paper's figure has ink) with their
labels where the paper has them, its rules and marks (logos) as plain
shapes.

    python3 twins.py OUT_DIR [NAME ...]

Standard library only.
"""

import json
import math
import random
import sys
from pathlib import Path

PAGES = Path(__file__).parent / "pages"

# Helvetica's widths (thousandths of the font size).
WIDTHS = dict(
    zip(
        "abcdefghijklmnopqrstuvwxyz ",
        [556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833]
        + [556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 278],
        strict=True,
    )
)
LETTERS = "etaoinshrdlcumwfgypbvk"


def words(rng: random.Random, width: float, size: float) -> tuple[str, float]:
    """Filler words for a line ``width`` points wide at ``size``: the text and
    the horizontal scaling (percent) that makes it exactly that wide."""
    text = ""
    natural = 0.0
    while natural < width or not text:
        word = "".join(rng.choice(LETTERS) for _ in range(rng.randint(2, 9)))
        text = f"{text} {word}" if text else word
        natural = sum(WIDTHS[c] for c in text) * size / 1000
    return text, max(30.0, min(300.0, 100 * width / natural))


def colour(rng: random.Random) -> str:
    """A colour dark enough to count as ink (``inkOf``)."""
    hue = rng.random()
    r, g, b = (
        0.25 + 0.45 * (0.5 + 0.5 * math.cos(2 * math.pi * (hue + k / 3)))
        for k in range(3)
    )
    return f"{r:.2f} {g:.2f} {b:.2f}"


def box(spec: dict, b: list[float]) -> tuple[float, float, float, float]:
    """A box from the page's top left (spec) in PDF points: x, y, w, h."""
    height = spec["size"][1]
    return b[0], height - b[3], b[2] - b[0], b[3] - b[1]


def page_stream(spec: dict) -> str:
    rng = random.Random(spec["name"])
    out: list[str] = []
    for figure in spec["figures"]:
        if figure.get("ink"):
            # Its silhouette: a coloured cell where the paper's figure has
            # ink, a gap where it has none.
            x, y, w, h = box(spec, figure["box"])
            cells = figure["ink"]
            cw, ch = w / len(cells[0]), h / len(cells)
            out.append(f"{colour(rng)} rg")
            for r, row in enumerate(cells):
                for c, cell in enumerate(row):
                    if cell == "1":
                        out.append(
                            f"{x + c * cw:.1f} {y + h - (r + 1) * ch:.1f} {cw:.1f} {ch:.1f} re f"
                        )
            continue
        for panel in figure["panels"]:
            x, y, w, h = box(spec, panel["box"])
            if panel["kind"] == "picture":
                out.append(f"{colour(rng)} rg {x:.1f} {y:.1f} {w:.1f} {h:.1f} re f")
                continue
            # A drawing: a frame and a few curves across it.
            out.append(f"{colour(rng)} RG 0.8 w {x:.1f} {y:.1f} {w:.1f} {h:.1f} re S")
            for _ in range(rng.randint(1, 3)):
                points = [
                    (
                        x + w * t / 12,
                        y + h * (0.5 + 0.4 * math.sin(t / 2 + rng.random() * 6)),
                    )
                    for t in range(13)
                ]
                path = " ".join(
                    f"{px:.1f} {py:.1f} {'m' if i == 0 else 'l'}"
                    for i, (px, py) in enumerate(points)
                )
                out.append(f"{colour(rng)} RG 1 w {path} S")
    for mark in spec["marks"]:
        x, y, w, h = box(spec, mark["box"])
        out.append(f"{colour(rng)} rg {x:.1f} {y:.1f} {w:.1f} {h:.1f} re f")
    for rule in spec["rules"]:
        x, y, w, h = box(spec, rule)
        out.append(f"0 0 0 RG {max(0.4, min(w, h)):.1f} w")
        out.append(
            f"{x:.1f} {y + h / 2:.1f} m {x + w:.1f} {y + h / 2:.1f} l S"
            if w >= h
            else f"{x + w / 2:.1f} {y:.1f} m {x + w / 2:.1f} {y + h:.1f} l S"
        )
    out.append("0 0 0 rg")
    for line in spec["lines"]:
        x, y, w, h = box(spec, line["box"])
        size = max(3.0, line["size"])
        text, scale = words(rng, w, size)
        out.append(
            f"BT /F1 {size:.1f} Tf {scale:.1f} Tz {x:.1f} {y + 0.22 * h:.1f} Td ({text}) Tj ET"
        )
    return "\n".join(out)


def pdf(spec: dict) -> bytes:
    width, height = spec["size"]
    stream = page_stream(spec).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
        "/Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>".encode(),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    wanted = set(sys.argv[2:])
    for path in sorted(PAGES.glob("*.json")):
        spec = json.loads(path.read_text())
        if not wanted or spec["name"] in wanted:
            (out / f"{spec['name']}.pdf").write_bytes(pdf(spec))


if __name__ == "__main__":
    main()
