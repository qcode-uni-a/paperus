"""What fluent mode must get right on a layout twin (``twins.py``): its
lines read in their order, every figure whole in one piece, the running
headers and footers left out."""

import itertools
from typing import Any

from paperus.page_layout import Piece

type Box = list[float]
"""A box from the page's top left (PDF points): x0, y0, x1, y1."""


def middle(box: Box) -> tuple[float, float]:
    """A box's middle (the order lines are read in: down, then across)."""
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def check(
    spec: dict[str, Any], columns: bool, pieces: list[Piece]
) -> tuple[list[str], list[int]]:
    """What is wrong (nothing: right), and each line's piece (its index in
    reading order, -1 for none)."""
    problems: list[str] = []

    def holds(piece: Piece, at: tuple[float, float]) -> bool:
        x, y = at
        return (
            piece["x"] <= x <= piece["x"] + piece["width"]
            and piece["y"] <= y <= piece["y"] + piece["height"]
        )

    piece_of = [
        next((i for i, p in enumerate(pieces) if holds(p, middle(line["box"]))), -1)
        for line in spec["lines"]
    ]

    if "columns" in spec and columns != spec["columns"]:
        problems.append(f"read as {'two columns' if columns else 'one column'}")
    # A page whose paragraphs are each one piece (double-spaced lines).
    if len(pieces) > spec.get("most_pieces", len(pieces)):
        problems.append(f"{len(pieces)} pieces (at most {spec['most_pieces']})")

    # Body lines: each in a piece, read in order (piece after piece, down
    # each piece, left to right on a line).
    body = [
        (line, piece_of[i], middle(line["box"]))
        for i, line in enumerate(spec["lines"])
        if line["role"] == "body"
    ]
    lost = [line for line, piece, _ in body if piece < 0]
    if lost:
        orders = ", ".join(str(line["order"]) for line in lost)
        problems.append(f"{len(lost)} lines in no piece (orders {orders})")
    read = sorted(
        (b for b in body if b[1] >= 0), key=lambda b: (b[1], b[2][1], b[2][0])
    )
    for (before, was, _), (now, piece, _) in itertools.pairwise(read):
        if now["order"] < before["order"]:
            problems.append(
                f"line {now['order']} (piece {piece}) read after line "
                f"{before['order']} (piece {was})"
            )
            if len(problems) > 8:
                break

    # Pieces side by side or one after another, not over each other (their
    # half-line margins aside).
    for i, a in enumerate(pieces):
        for k, b in enumerate(pieces[i + 1 :]):
            w = min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])
            h = min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"])
            smaller = min(a["width"] * a["height"], b["width"] * b["height"])
            if w > 8 and h > 8 and w * h > smaller * 0.25:
                problems.append(f"pieces {i} and {i + 1 + k} overlap")

    # Running headers and footers: in no piece.
    for i, line in enumerate(spec["lines"]):
        if line["role"] == "furniture" and piece_of[i] >= 0:
            problems.append(
                f"header or footer at y {round(line['box'][1])} kept "
                f"(piece {piece_of[i]})"
            )

    # Figures: whole in one piece (or each of their parts).
    for n, figure in enumerate(spec["figures"]):
        for x0, y0, x1, y1 in figure.get("parts") or [figure["box"]]:
            size = (x1 - x0) * (y1 - y0)
            best = 0.0
            for p in pieces:
                w = min(x1, p["x"] + p["width"]) - max(x0, p["x"])
                h = min(y1, p["y"] + p["height"]) - max(y0, p["y"])
                if w > 0 and h > 0:
                    best = max(best, w * h / size)
            if best < 0.9:
                problems.append(
                    f"figure {n + 1} split (at most {round(best * 100)}% in one piece)"
                )
    return problems, piece_of
