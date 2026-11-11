"""Fluent mode on layout twins of real papers' pages (``twins/``): each
built (``twins.py``), read as the worker reads a page, and checked
(``twins/check.py``). A twin with a ``todo`` is a known gap: expected to
fail, and told when it passes."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pypdfium2
import pytest

from paperus import page_layout
from paperus.page_layout import analyse, lay_out
from tests.twins import twins
from tests.twins.check import check

SPECS = sorted(
    (json.loads(path.read_text()) for path in twins.PAGES.glob("*.json")),
    key=lambda spec: spec["name"],
)


def read(spec: dict[str, Any], tmp_path: Path) -> tuple[bool, list[Any]]:
    path = tmp_path / f"{spec['name']}.pdf"
    path.write_bytes(twins.pdf(spec))
    with pypdfium2.PdfDocument(path) as pdf:
        layout = analyse(pdf[0], spec["first"])
    return layout["columns"], layout["pieces"]


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param(
            spec,
            id=spec["name"],
            marks=[pytest.mark.xfail(reason=spec["todo"], strict=True)]
            if spec.get("todo")
            else [],
        )
        for spec in SPECS
    ],
)
def test_twin(spec: dict[str, Any], tmp_path: Path) -> None:
    columns, pieces = read(spec, tmp_path)
    problems, _ = check(spec, columns, pieces)
    assert not problems, "\n".join(problems)


def test_a_title_in_large_type_is_no_columns() -> None:
    """A title's words either side of a gap in a part across the page (the
    gap where the columns below have none): across the page still, known
    by its type size."""
    ink = np.zeros((800, 600), dtype=bool)
    sizes = np.zeros((800, 600), dtype=np.float32)

    def line(x0: int, x1: int, y0: int, y1: int, size: float) -> None:
        # Letters: ink with thin gaps, as text has.
        ink[y0:y1, x0:x1] = (np.arange(x0, x1) % 4 != 0)[None, :]
        sizes[y0:y1, x0:x1] = size

    for y in (60, 100, 140):
        line(60, 360, y, y + 28, 30)
        line(378, 540, y, y + 28, 30)
    for y in range(200, 700, 12):
        line(60, 290, y, y + 8, 9)
        line(310, 540, y, y + 8, 9)
    columns, pieces = lay_out(ink, True, sizes)
    assert columns
    title = [p for p in pieces if p["y"] < 180]
    assert title
    assert all(p["wide"] for p in title)
    # Not known without the sizes: in two "columns".
    _, unsized = page_layout.lay_out(ink, True, sizes.astype(bool))
    assert not all(p["wide"] for p in unsized if p["y"] < 180)


def test_a_third_column_beside_the_title_is_one_piece() -> None:
    """Science's first page: the title over two columns, the third column
    from the top; it is read whole, after the second."""
    ink = np.zeros((760, 600), dtype=bool)
    sizes = np.zeros((760, 600), dtype=np.float32)

    def column(x0: int, x1: int, y0: int, y1: int) -> None:
        for y in range(y0, y1, 11):
            ink[y : y + 7, x0:x1] = (np.arange(x0, x1) % 4 != 0)[None, :]
            sizes[y : y + 7, x0:x1] = 9

    column(40, 380, 50, 220)  # title and abstract over the first two
    column(40, 200, 240, 700)
    column(220, 380, 240, 440)
    column(400, 560, 50, 440)  # the third, from the top
    ink[470:700, 230:560] = True  # a figure under the second and third
    _, pieces = lay_out(ink, False, sizes)
    third = [p for p in pieces if p["x"] > 390]
    assert len(third) == 1
    assert third[0]["y"] < 60
    assert third[0]["y"] + third[0]["height"] > 430
    assert pieces.index(third[0]) == len(pieces) - 2  # before the figure


def test_an_equation_between_revtex_rules_is_across() -> None:
    """REVTeX's wide equation: a rule closes the left column (a tick up by
    the gap), the equation runs across, a rule opens the right column (a
    tick down); the matrix leaves the gap blank. Read: both columns above,
    the equation, both columns below."""
    ink = np.zeros((792, 612), dtype=bool)

    def column(x0: int, x1: int, y0: int, y1: int) -> None:
        for y in range(y0, y1, 11):
            ink[y : y + 7, x0:x1] = (np.arange(x0, x1) % 4 != 0)[None, :]

    column(50, 297, 60, 410)
    column(314, 561, 60, 410)
    ink[422, 51:297] = True  # closing rule
    ink[418:422, 296] = True  # its tick
    for y in range(428, 488, 14):  # the matrix's rows, either side
        ink[y : y + 8, 90:280] = (np.arange(90, 280) % 7 != 0)[None, :]
        ink[y : y + 8, 330:520] = (np.arange(330, 520) % 7 != 0)[None, :]
    ink[494, 314:561] = True  # opening rule
    ink[495:499, 314] = True  # its tick
    column(50, 297, 506, 740)
    column(314, 561, 506, 740)
    columns, pieces = lay_out(ink)
    assert columns
    found = [(p["x"] < 300, p["y"] // 100, p["wide"]) for p in pieces]
    assert found == [
        (True, 0, False),
        (False, 0, False),
        (True, 4, True),
        (True, 5, False),
        (False, 5, False),
    ]
    # Begun on the page before: across from the top to the opening rule.
    ink[418:423, 51:297] = False
    _, pieces = lay_out(ink)
    found = [(p["x"] < 300, p["y"] // 100, p["wide"]) for p in pieces]
    assert found == [
        (True, 0, True),
        (True, 4, True),
        (True, 5, False),
        (False, 5, False),
    ]
    # Tables' double rules over a column are no such rules.
    ink[418:422, 296] = False
    ink[420, 51:297] = True
    ink[495:499, 314] = False
    ink[496, 314:561] = True
    _, pieces = lay_out(ink)
    assert not any(p["wide"] for p in pieces)


def test_an_equation_over_a_few_lines_is_no_columns() -> None:
    """A one-column page's equation running on over five lines, its terms
    aligned (gaps down all its lines): across, not in columns."""
    ink = np.zeros((792, 612), dtype=bool)

    def text(y0: int, y1: int) -> None:
        for y in range(y0, y1, 14):
            ink[y : y + 8, 70:540] = (np.arange(70, 540) % 4 != 0)[None, :]

    text(60, 500)
    for y in range(520, 620, 24):  # the equation's lines, in three parts
        for x0, x1 in ((80, 250), (262, 400), (412, 540)):
            ink[y : y + 16, x0:x1] = (np.arange(x0, x1) % 5 != 0)[None, :]
    text(640, 740)
    columns, pieces = lay_out(ink)
    assert not columns
    assert all(p["wide"] for p in pieces)


def test_a_few_column_lines_under_a_figure_are_columns() -> None:
    """A figure across the page, its caption, and five lines in two columns
    under it (too few for the page's own gap): read in their columns, not
    as part of the figure. A caption whose word spaces line up for a few
    lines stays whole."""
    ink = np.zeros((792, 612), dtype=bool)
    sizes = np.zeros((792, 612), dtype=np.float32)

    def lines(x0: int, x1: int, y0: int, y1: int) -> None:
        for y in range(y0, y1, 12):
            ink[y : y + 8, x0:x1] = (np.arange(x0, x1) % 4 != 0)[None, :]
            sizes[y : y + 8, x0:x1] = 9

    ink[60:600, 60:550:3] = True  # the figure: drawing, no text
    lines(50, 562, 615, 680)  # its caption
    lines(50, 297, 700, 760)
    lines(314, 562, 700, 760)
    _, pieces = lay_out(ink, False, sizes)
    found = [(p["x"] < 300, p["y"] > 690, p["wide"]) for p in pieces]
    assert found == [(True, False, True), (True, True, False), (False, True, False)]

    # The five lines' gap crossed by the caption's lines around them.
    lines(50, 562, 615, 690)
    lines(50, 562, 760, 784)
    _, pieces = lay_out(ink, False, sizes)
    assert all(p["wide"] for p in pieces)
