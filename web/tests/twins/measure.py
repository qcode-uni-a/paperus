"""Measure a page of a real paper as a layout twin's spec: where its lines
of text, figures, rules and marks are, and the order its lines are read in,
without any of its words or pictures (``twins.py`` builds the twin from it).

Run from ``server/`` (it needs PDFium)::

    uv run python ../web/tests/twins/measure.py PAPER.pdf PAGE NAME "Where from"

It writes ``pages/NAME.json``. Look the twin over (``review.ts``) before
it becomes a test: the expected order is the paper's own text order, and
which lines are running headers and footers is a guess.
"""

import ctypes
import json
import re
import sys
from pathlib import Path
from statistics import median

import pypdfium2 as pdfium
from pypdfium2 import raw

PAGES = Path(__file__).parent / "pages"
# Running headers and footers sit in these bands at the top and bottom.
EDGE = 0.09
# A figure's parts (panels) at most this far apart (points).
PANEL_GAP = 3
FIGURE_GAP = 24
# A figure's silhouette: where it has ink, in cells this large (points).
CELL = 6


def lines_of(page: pdfium.PdfPage, turned: list | None = None) -> list[dict]:
    """The page's lines of text, in the order the PDF holds them: box (PDF
    points, origin at the lower left), font size, words (for telling
    running headers apart), first character's index. Turned text (arXiv's
    stamp in the margin) goes to ``turned`` as boxes instead."""
    text = page.get_textpage()
    lines: list[dict] = []
    line: dict | None = None
    for i in range(text.count_chars()):
        char = text.get_text_range(i, 1)
        if char in "\r\n":
            line = None
            continue
        if abs(raw.FPDFText_GetCharAngle(text.raw, i)) > 0.1:
            if turned is not None and not char.isspace():
                turned.append(list(text.get_charbox(i, loose=True)))
            line = None
            continue
        # The font's box (all characters of a line alike): its height is
        # the size, whatever the PDF's own font size says.
        left, bottom, right, top = text.get_charbox(i, loose=True)
        size = top - bottom
        if char.isspace() or right <= left:
            if line:
                line["text"] += " "
            continue
        middle = (bottom + top) / 2
        if (
            line is None
            or abs(middle - line["middle"]) > 0.6 * max(size, line["size"])
            or left < line["box"][2] - size
            or left > line["box"][2] + 3 * size
        ):
            line = {
                "box": [left, bottom, right, top],
                "sizes": [],
                "text": "",
                "first": i,
            }
            line["middle"] = middle
            lines.append(line)
        box = line["box"]
        line["box"] = [
            min(box[0], left),
            min(box[1], bottom),
            max(box[2], right),
            max(box[3], top),
        ]
        line["sizes"].append(size)
        line["size"] = median(line["sizes"])
        line["text"] += char
    return lines


def near(a: list[float], b: list[float], gap: float) -> bool:
    return (
        a[0] - gap <= b[2]
        and b[0] - gap <= a[2]
        and a[1] - gap <= b[3]
        and b[1] - gap <= a[3]
    )


def joined(boxes: list[dict], gap: float) -> list[dict]:
    """Boxes closer than ``gap`` joined (and joined groups that come close),
    until none are. Neighbours first, through a grid: pages with plots hold
    thousands of shapes."""
    parent = list(range(len(boxes)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cell = max(gap, 24.0)
    grid: dict[tuple[int, int], list[int]] = {}
    for i, b in enumerate(boxes):
        x0, y0, x1, y1 = b["box"]
        for gx in range(int((x0 - gap) // cell), int((x1 + gap) // cell) + 1):
            for gy in range(int((y0 - gap) // cell), int((y1 + gap) // cell) + 1):
                for j in grid.setdefault((gx, gy), []):
                    if root(i) != root(j) and near(b["box"], boxes[j]["box"], gap):
                        parent[root(i)] = root(j)
                grid[(gx, gy)].append(i)
    groups: dict[int, dict] = {}
    for i, b in enumerate(boxes):
        g = groups.setdefault(root(i), {"box": list(b["box"]), "parts": []})
        g["box"] = [min(g["box"][0], b["box"][0]), min(g["box"][1], b["box"][1])] + [
            max(g["box"][2], b["box"][2]),
            max(g["box"][3], b["box"][3]),
        ]
        g["parts"].append(b)
    out = list(groups.values())
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(out):
            for c in out[i + 1 :]:
                if near(a["box"], c["box"], gap):
                    a["box"] = [
                        min(a["box"][0], c["box"][0]),
                        min(a["box"][1], c["box"][1]),
                    ] + [
                        max(a["box"][2], c["box"][2]),
                        max(a["box"][3], c["box"][3]),
                    ]
                    a["parts"] += c["parts"]
                    out.remove(c)
                    changed = True
                    break
            if changed:
                break
    return out


def blank(obj: pdfium.PdfObject) -> bool:
    """A path only filled, in white (a frame behind a figure): no ink."""
    if obj.type != raw.FPDF_PAGEOBJ_PATH:
        return False
    fill, stroke = ctypes.c_int(), ctypes.c_int()
    if not raw.FPDFPath_GetDrawMode(obj.raw, fill, stroke) or stroke.value:
        return False
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    if not raw.FPDFPageObj_GetFillColor(obj.raw, r, g, b, a):
        return False
    return not fill.value or min(r.value, g.value, b.value) > 235 or a.value < 20


def drawings_of(page: pdfium.PdfPage, width: float, height: float) -> tuple[list, list]:
    """Rules (thin lines) and the drawn or pictured parts of the page."""
    rules, parts = [], []
    kinds = {raw.FPDF_PAGEOBJ_PATH: "drawing", raw.FPDF_PAGEOBJ_IMAGE: "picture"}
    kinds[raw.FPDF_PAGEOBJ_SHADING] = "picture"
    for obj in page.get_objects(max_depth=4):
        kind = kinds.get(obj.type)
        if kind is None:
            continue
        left, bottom, right, top = obj.get_bounds()
        w, h = right - left, top - bottom
        if w * h > width * height * 0.8 or blank(obj):
            continue  # a background, a white frame
        if h < 1.5 and w > 15 or w < 1.5 and h > 15:
            rules.append([left, bottom, right, top])
        elif w >= 1 and h >= 1:
            parts.append({"box": [left, bottom, right, top], "kind": kind})
    return rules, parts


def silhouette(
    page: pdfium.PdfPage, box: list[float], labels: list[list[float]]
) -> list[str]:
    """Where a figure has ink, in cells of CELL points (rows from the top,
    "1" ink): its panels and the gaps between them, not its picture. Its
    labels (lines of text) are left out; the twin writes them."""
    bitmap = page.render(scale=1, grayscale=True)
    pixels, stride = bytes(bitmap.buffer), bitmap.stride
    height = page.get_size()[1]
    left, top = box[0], height - box[3]
    columns = max(1, round((box[2] - box[0]) / CELL))
    rows = max(1, round((box[3] - box[1]) / CELL))

    def labelled(x: float, y: float) -> bool:
        return any(
            lb[0] <= x <= lb[2] and height - lb[3] <= y <= height - lb[1]
            for lb in labels
        )

    out = []
    for r in range(rows):
        row = ""
        for c in range(columns):
            x0, y0 = int(left + c * CELL), int(top + r * CELL)
            ink = total = 0
            for y in range(y0, min(y0 + CELL, bitmap.height)):
                for x in range(x0, min(x0 + CELL, bitmap.width)):
                    total += 1
                    ink += pixels[y * stride + x] < 215
            centre = (x0 + CELL / 2, y0 + CELL / 2)
            row += (
                "1" if total and ink / total > 0.12 and not labelled(*centre) else "0"
            )
        out.append(row)
    return out


def plain(text: str) -> str:
    return re.sub(r"[\d\s]+", "", text.lower())


def measure(path: Path, number: int) -> dict:
    pdf = pdfium.PdfDocument(path)
    page = pdf[number - 1]
    width, height = page.get_size()
    turned: list = []
    lines = lines_of(page, turned)
    rules, parts = drawings_of(page, width, height)

    # Panels: drawn parts touching each other; figures: panels close by,
    # with the lines of text among them (labels, axes).
    # Shapes at the very edge (a header's bar, a journal's side tab) are no
    # figure's.
    edge_parts = [
        p
        for p in parts
        if p["box"][1] > height * 0.93
        or p["box"][3] < height * 0.06
        or p["box"][2] < width * 0.07
        or p["box"][0] > width * 0.93
    ]
    parts = [p for p in parts if p not in edge_parts]
    panels = [
        {
            "box": g["box"],
            "kind": "picture"
            if any(p["kind"] == "picture" for p in g["parts"])
            else "drawing",
        }
        for g in joined(parts, PANEL_GAP)
        if (g["box"][2] - g["box"][0]) * (g["box"][3] - g["box"][1]) >= 60
    ]
    figures = [
        {"box": g["box"], "panels": g["parts"]}
        for g in joined(panels, FIGURE_GAP)
        if (g["box"][2] - g["box"][0]) * (g["box"][3] - g["box"][1]) >= 900
    ]

    # Drawn things at the page's top or bottom edge (a journal's banner, a
    # header's rule, a logo) are marks, not figures.
    def at_edge(box: list[float]) -> bool:
        return box[1] > height * (1 - 0.15) or box[3] < height * 0.1

    marked = [f for f in figures if at_edge(f["box"])]
    figures = [f for f in figures if f not in marked]
    small = [p for p in panels if not any(p in f["panels"] for f in figures)]
    small += [
        {"box": g["box"], "kind": "text"}
        for g in joined([{"box": b} for b in turned], 4)
    ]
    small += [
        {"box": g["box"], "kind": "drawing"} for g in joined(edge_parts, PANEL_GAP)
    ]

    def inside(box: list[float], outer: list[float]) -> bool:
        x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        return outer[0] - 2 <= x <= outer[2] + 2 and outer[1] - 2 <= y <= outer[3] + 2

    # Running headers and footers: at the top or bottom edge, numbers only
    # or the same words at the same place on another page.
    others = [
        line
        for n in range(max(1, number - 3), min(len(pdf), number + 3) + 1)
        if n != number
        for line in lines_of(pdf[n - 1])
    ]

    def edge(box: list[float]) -> bool:
        return box[3] > height * (1 - EDGE) or box[1] < height * EDGE

    def furniture(line: dict) -> bool:
        if not edge(line["box"]):
            return False
        words = plain(line["text"])
        return not words or any(
            plain(o["text"]) == words and abs(o["box"][1] - line["box"][1]) < 15
            for o in others
        )

    def flip(box: list[float]) -> list[float]:
        """PDF points from the page's top left, rounded."""
        return [
            round(box[0], 1),
            round(height - box[3], 1),
            round(box[2], 1),
            round(height - box[1], 1),
        ]

    # Small text close to a figure (axis titles, panel labels outside its
    # picture) is the figure's.
    usual = median(line["size"] for line in lines) if lines else 10
    for figure in figures:
        for line in lines:
            if line["size"] < usual * 0.9 and near(line["box"], figure["box"], 10):
                b, f = line["box"], figure["box"]
                figure["box"] = [
                    min(b[0], f[0]),
                    min(b[1], f[1]),
                    max(b[2], f[2]),
                    max(b[3], f[3]),
                ]

    out_lines = []
    order = 0
    for line in lines:
        if any(inside(line["box"], f["box"]) for f in figures) or any(
            inside(line["box"], m["box"]) for m in small
        ):
            role = "figure"
        elif furniture(line):
            role = "furniture"
        else:
            role = "body"
        entry = {"box": flip(line["box"]), "size": round(line["size"], 1), "role": role}
        if role == "body":
            entry["order"] = order
            order += 1
        out_lines.append(entry)
    return {
        "size": [round(width, 1), round(height, 1)],
        "first": number == 1,
        "lines": out_lines,
        "figures": [
            {
                "box": flip(f["box"]),
                "panels": [
                    {"box": flip(p["box"]), "kind": p["kind"]} for p in f["panels"]
                ],
                "ink": silhouette(
                    page,
                    f["box"],
                    [line["box"] for line in lines if inside(line["box"], f["box"])],
                ),
            }
            for f in figures
        ],
        "marks": [{"box": flip(p["box"]), "kind": p["kind"]} for p in small],
        "rules": [flip(r) for r in rules],
    }


def main() -> None:
    path, number, name, source = (
        Path(sys.argv[1]),
        int(sys.argv[2]),
        sys.argv[3],
        sys.argv[4],
    )
    spec = {"name": name, "source": source, **measure(path, number)}
    PAGES.mkdir(exist_ok=True)
    (PAGES / f"{name}.json").write_text(json.dumps(spec, indent=1) + "\n")
    lines = spec["lines"]
    print(
        f"{name}: {len(lines)} lines ({sum(line['role'] == 'furniture' for line in lines)} header/footer), "
        f"{len(spec['figures'])} figures, {len(spec['rules'])} rules, {len(spec['marks'])} marks"
    )


if __name__ == "__main__":
    main()
