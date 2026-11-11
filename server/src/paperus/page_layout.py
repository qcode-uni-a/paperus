"""Fluent mode's page layouts: a paper's pages cut into pieces in reading
order, so that on a narrow screen one column fills it and the columns run
on into each other (a part across the page, then the left column, the right
column, …), without margins, running headers and footers. Worked out once
per file content by the worker (``jobs.page_layout``), shown by the website
(``web/src/lib/ColumnView.svelte``).

Found from where a page has ink, drawn at one pixel per PDF point: the
page's body is cut into blocks at blank space; in each block, the gap
between two columns is a strip near the middle that its lines do not cross,
and the rows crossing it (a title, an abstract, a figure over both columns)
stay whole. A part in one column keeps only its own ink.

Tested on layout twins of real papers' pages (``tests/twins/``). Raise
``VERSION`` with every change that changes layouts: stored ones of older
versions are made again (``jobs.queue_outdated_layouts``).
"""

import ctypes
import itertools
import math
from dataclasses import dataclass
from typing import Any, TypedDict

import numpy as np
import pypdfium2
import pypdfium2.raw as pdfium_c

VERSION = 5
"""The layouts this code makes (stored with them)."""

# Narrower ink at a page's side is a margin note (arXiv's stamp, line
# numbers), not the page's body.
MARGIN_NOTE = 30
# Blank space that separates ink across the page (points).
SIDE_GAP = 8
# The gap between columns is at least this wide.
GUTTER = 6
# Rows reaching into the gap between columns leave at least this much of it
# blank, else they are across it.
NARROW_GAP = 4
# Blank space between a table's columns, down all its rows, at least.
TABLE_GAP = 6
# How far a line's ink reaches beyond its middle part (points).
LINE_REACH = 5
# Blank space between blocks of the page, each with its own columns.
BLOCK_SPLIT = 9
# Lines this many times as tall as the page's usual one are in display
# type (a title), not a column's.
DISPLAY_TYPE = 1.6
# ... or than this many times the page's usual space between lines.
DOUBLE_SPACED = 1.6
# A figure's panels are at most this far apart.
FIGURE_GAP = 30
# One side of a page's columns holding two of three: wider than this share
# of the body (two columns' sides are each about half).
THIRD_COLUMN_SIDE = 0.55
# Points of blank space inside a line of text at most (word spaces of a
# justified line; an equation's parts stand further apart).
LINE_GAP = 24
# REVTeX's wide equations: a rule closing the left column, a tick up at its
# end by the gap, and one opening the right column below, a tick down at
# its start; each across this share of its column at least, ending this
# close to the gap found (points: as wide as a gap between columns, as the
# equation may narrow the gap found).
WIDE_RULE = 0.85
WIDE_RULE_GAP = 16
WIDE_TICK = 3
# A rule over the columns' gap ending them: at least this share of the
# width long.
RULE_ACROSS = 0.2
RULE_ACROSS_MOST = 0.8
# A stretch of two columns is at least this tall (a few lines).
MIN_COLUMNS = 36
# A running header or footer: a block of a line or two (with a rule, a
# small logo) at the page's top or bottom edge, set apart from the body.
EDGE_BLOCK = 40
EDGE = 0.09
# A logo or mark in a corner, leaving the middle empty, may be taller.
CORNER_BLOCK = 70
CORNER_EDGE = 0.14
# A page number centred under the text: one short line (points), in the
# page's lower part (LaTeX sets it well above the edge band), narrow and
# about in the middle (shares of the text's width).
PAGE_NUMBER_SPAN = 14
PAGE_NUMBER_EDGE = 0.2
PAGE_NUMBER_WIDTH = 0.08
PAGE_NUMBER_OFF_CENTRE = 0.05
# It may sit this close under the text (IEEE's, under the columns).
PAGE_NUMBER_GAP = 3
# Lines closer than this belong to one block.
BLOCK_GAP = 6
# Long thin upright lines are at least this tall.
UPRIGHT = 80
# A rule drawn at most this many rows thick (and one more).
RULE_ROWS = 5
# Ink: pixels darker than this (0 black, 255 white).
INK_LIGHT = 190


class Piece(TypedDict):
    """A part of a page, in PDF points from its top left."""

    x: int
    y: int
    width: int
    height: int
    wide: bool
    """Across the page's width (else one column)."""
    span: int
    """The width that fills the screen: the body's for a wide piece, the
    wider column's for a column (both columns' text the same size)."""


class PageLayout(TypedDict):
    width: float
    height: float
    columns: bool
    """The page is set in two columns (over a good part of it)."""
    pieces: list[Piece]


type Run = list[int]
"""A run of rows or columns: [start, end], both included."""


def _round(value: float) -> int:
    """Rounded as JavaScript's Math.round does (halves up)."""
    return math.floor(value + 0.5)


def runs(values: Any, start: int = 0, end: int | None = None) -> list[Run]:  # noqa: ANN401 (a sequence or an array of booleans)
    """Runs of true values between ``start`` and ``end`` (included)."""
    flags = np.asarray(values, dtype=bool)
    end = len(flags) - 1 if end is None else end
    part = flags[max(0, start) : end + 1]
    if not part.size:
        return []
    edges = np.diff(np.concatenate(([0], part.astype(np.int8), [0])))
    return [
        [int(a) + start, int(b) + start - 1]
        for a, b in zip(
            np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True
        )
    ]


def joined(found: list[Run], gap: int) -> list[Run]:
    """Runs joined where the space between them is smaller than ``gap``."""
    out: list[Run] = []
    for run in found:
        if out and run[0] - out[-1][1] - 1 < gap:
            out[-1][1] = run[1]
        else:
            out.append(list(run))
    return out


def without_uprights(ink: np.ndarray) -> np.ndarray:
    """Long thin upright lines (a rule between columns, a box's side, a
    plot's axis) left out: across them every row has ink, as if the page
    were one line."""
    out = ink.copy()
    width = ink.shape[1]
    tall = np.flatnonzero(ink.sum(axis=0) >= UPRIGHT)
    for x in tall:
        for y0, y1 in runs(ink[:, x]):
            if y1 - y0 + 1 < UPRIGHT:
                continue
            # Thin: little ink a few points either side along it.
            beside = 0
            if x >= 3:
                beside += int(ink[y0 : y1 + 1, x - 3].sum())
            if x + 3 < width:
                beside += int(ink[y0 : y1 + 1, x + 3].sum())
            if beside < (y1 - y0 + 1) * 0.4:
                out[y0 : y1 + 1, max(0, x - 1) : min(width, x + 2)] = 0
    return out


def longest(row: np.ndarray) -> int:
    """The longest unbroken stretch of ink in a row."""
    return max((b - a + 1 for a, b in runs(row)), default=0)


def _sums(values: np.ndarray) -> np.ndarray:
    """Sums of all values above and left of each point (one more row and
    column), for any rectangle's sum at once."""
    sums = np.zeros((values.shape[0] + 1, values.shape[1] + 1), dtype=np.int64)
    sums[1:, 1:] = values.cumsum(axis=0, dtype=np.int64).cumsum(axis=1)
    return sums


@dataclass
class _Band:
    y0: int
    y1: int
    wide: bool


@dataclass
class _Box:
    x0: int
    x1: int
    y0: int
    y1: int
    wide: bool = False
    span: int = 0


def lay_out(
    ink: np.ndarray, first: bool = False, text: np.ndarray | None = None
) -> tuple[bool, list[Piece]]:
    """A page's pieces from its ink (rows by columns of booleans, one pixel a
    point), and whether it is set in two columns. ``first``: the document's
    first page (its top line is a title, not a running header). ``text``:
    where the page has text, its type size there (points; else its ink
    outside them is not known as drawing, nor large type)."""
    height, width = ink.shape
    ink = without_uprights(ink.astype(bool))
    sizes = text if text is not None and text.dtype != bool else None
    text = text.astype(bool) if text is not None else None
    # The page's usual type size, to tell large type (a title) from it.
    large = (
        float(np.median(sizes[sizes > 0])) * DISPLAY_TYPE
        if sizes is not None and (sizes > 0).any()
        else math.inf
    )
    all_ink = _sums(ink)
    drawn_ink = _sums(ink & ~text) if text is not None else all_ink
    text_ink = ink & text if text is not None else ink

    def total(sums: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> int:
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(width - 1, x1), min(height - 1, y1)
        if x1 < x0 or y1 < y0:
            return 0
        return int(
            sums[y1 + 1, x1 + 1] - sums[y0, x1 + 1] - sums[y1 + 1, x0] + sums[y0, x0]
        )

    def drawn(x0: int, x1: int, y0: int, y1: int, share: float = 0.5) -> bool:
        """Mostly drawn, not written: a figure (its ink outside the page's
        text boxes)."""
        if text is None:
            return False
        count = total(all_ink, x0, x1, y0, y1)
        return count > 50 and total(drawn_ink, x0, x1, y0, y1) > count * share

    def area(x0: int, x1: int, y0: int, y1: int) -> np.ndarray:
        return ink[max(0, y0) : y1 + 1, max(0, x0) : x1 + 1]

    # The body across: ink separated by blank space, without margin notes.
    across = joined(runs(ink.any(axis=0)), SIDE_GAP)
    # Pieces reach at most halfway to a margin note (a download line turned
    # upright beside the text, arXiv's stamp): none of it shows.
    note_left = -1
    note_right = width
    while len(across) > 1 and across[0][1] - across[0][0] < MARGIN_NOTE:
        note_left = across.pop(0)[1]
    while len(across) > 1 and across[-1][1] - across[-1][0] < MARGIN_NOTE:
        note_right = across.pop()[0]
    if not across:
        return False, []
    left = across[0][0]
    right = across[-1][1]
    leftmost = 0 if note_left < 0 else math.ceil((note_left + left) / 2)
    rightmost = width if note_right >= width else math.floor((right + note_right) / 2)
    body_width = right - left + 1

    # The body down: lines of ink; a running header and footer left out.
    ink_across = ink[:, left : right + 1].sum(axis=1)
    in_row = (ink_across > 0).tolist()

    def rule(y: int) -> bool:
        """A row inked across most of the body."""
        return ink_across[y] >= body_width * 0.8

    # A rule near the top or the bottom sets off a running header or
    # footer: it goes, with what lies beyond it.
    head_end = -1
    y = 0
    while y < height * EDGE:
        if in_row[y] and rule(y):
            head_end = y
        y += 1
    foot_start = height
    y = height - 1
    while y > height * (1 - EDGE):
        if in_row[y] and rule(y):
            foot_start = y
        y -= 1
    lines = runs(in_row, head_end + 1, foot_start - 1)
    if not lines:
        return False, []

    # Running headers and footers (page numbers, journal lines, logos) left
    # out: up to two blocks at each edge, apart from the body. On the first
    # page only a small one above the title, or a mark in a corner.
    def span(block: Run) -> int:
        return block[1] - block[0] + 1

    def page_number(block: Run) -> bool:
        if (
            span(block) > PAGE_NUMBER_SPAN
            or height - block[0] >= height * PAGE_NUMBER_EDGE
        ):
            return False
        inked = np.flatnonzero(area(left, right, block[0], block[1]).any(axis=0))
        x0, x1 = (
            (left + int(inked[0]), left + int(inked[-1]))
            if inked.size
            else (right, left)
        )
        # Centred under the text, or on the page (an equation reaching into
        # one margin moves the text's middle).
        middle = (x0 + x1) / 2
        off = body_width * PAGE_NUMBER_OFF_CENTRE
        return x1 - x0 <= body_width * PAGE_NUMBER_WIDTH and (
            abs(middle - (left + body_width / 2)) <= off
            or abs(middle - width / 2) <= off
        )

    # A page number close under the text (closer than lines of one block
    # are; IEEE's sits so under the columns) goes before lines are blocks.
    if len(lines) > 1:
        before, last = lines[-2], lines[-1]
        if last[0] - before[1] - 1 >= PAGE_NUMBER_GAP and page_number(last):
            lines.pop()
    blocks = joined(lines, BLOCK_GAP)
    middle_from = _round(left + body_width * 0.3)
    middle_to = _round(left + body_width * 0.7)

    def in_corner(block: Run) -> bool:
        return not area(middle_from, middle_to, block[0], block[1]).any()

    def edge_block(block: Run, at_top: bool) -> bool:
        reach = block[1] if at_top else height - block[0]
        if (
            in_corner(block)
            and span(block) <= CORNER_BLOCK
            and reach < height * CORNER_EDGE
        ):
            return True
        if reach >= height * EDGE:
            return False
        if at_top and first:
            return span(block) <= 12 and block[1] < height * 0.075
        return span(block) <= EDGE_BLOCK

    for _ in range(2):
        if len(blocks) <= 1:
            break
        head, after = blocks[0], blocks[1]
        if not edge_block(head, True) or after[0] - head[1] - 1 < SIDE_GAP:
            break
        blocks.pop(0)
    for _ in range(2):
        if len(blocks) <= 1:
            break
        foot, before = blocks[-1], blocks[-2]
        gap = foot[0] - before[1] - 1
        number = page_number(foot)
        if not (number or edge_block(foot, False)) or gap < (
            PAGE_NUMBER_GAP if number else SIDE_GAP
        ):
            break
        blocks.pop()
    lines = [line for line in lines if blocks[0][0] <= line[0] <= blocks[-1][1]]
    top = lines[0][0]
    bottom = lines[-1][1]
    # Half the usual space between lines, around each piece.
    spaces = sorted(
        space
        for space in (b[0] - a[1] - 1 for a, b in itertools.pairwise(lines))
        if space > 0
    )
    usual = spaces[len(spaces) // 2] if spaces else 4
    pad = min(8, max(2, _round(usual / 2)))
    # Blocks are set apart by more than the usual space between lines (a
    # double-spaced page's lines are one block).
    block_split = max(BLOCK_SPLIT, _round(usual * DOUBLE_SPACED))

    def ink_extent(x0: int, x1: int, y0: int, y1: int) -> _Box | None:
        part = area(x0, x1, y0, y1)
        rows = np.flatnonzero(part.any(axis=1))
        if not rows.size:
            return None
        columns = np.flatnonzero(part.any(axis=0))
        x0, y0 = max(0, x0), max(0, y0)
        return _Box(
            x0 + int(columns[0]),
            x0 + int(columns[-1]),
            y0 + int(rows[0]),
            y0 + int(rows[-1]),
        )

    def extent(x0: int, x1: int, y0: int, y1: int) -> _Box | None:
        """Ink of the rows ``y0``-``y1`` between ``x0`` and ``x1``: its
        extent, or None. A rule alone at its top or bottom edge, apart from
        the rest (the marks above and below an equation across both
        columns, a column's closing rule), is left out."""
        found = ink_extent(x0, x1, y0, y1)
        if found is None:
            return None

        def count(y: int) -> int:
            return int(area(x0, x1, y, y).sum())

        def stretch(y: int) -> int:
            """The longest unbroken stretch of ink in row ``y`` (a rule's
            is long; text breaks at every letter)."""
            return longest(area(x0, x1, y, y)[0])

        across = found.x1 - found.x0 + 1

        def past_rule(start: int, step: int, limit: int) -> int | None:
            """From the edge row ``start`` going ``step``: the first row past
            a rule standing alone there (a tick beside it allowed), or None."""

            def within(y: int) -> bool:
                return y >= limit if step < 0 else y <= limit

            y = start
            is_rule = False
            while within(y):
                n = count(y)
                if not n:
                    break
                if abs(y - start) > 8:
                    return None
                if stretch(y) >= across * 0.5:
                    is_rule = True
                elif n > across * 0.15:
                    return None  # a line of text
                y += step
            if not is_rule:
                return None
            while within(y) and not count(y):
                y += step
            return y if within(y) else None

        top, bottom = found.y0, found.y1
        moved = past_rule(top, 1, bottom)
        top = top if moved is None else moved
        moved = past_rule(bottom, -1, top)
        bottom = bottom if moved is None else moved
        if top == found.y0 and bottom == found.y1:
            return found
        return ink_extent(x0, x1, top, bottom)

    side_rows: dict[tuple[int, int], list[bool]] = {}

    def rows_in(x0: int, x1: int) -> list[bool]:
        """Which rows have ink between ``x0`` and ``x1`` (the body's:
        in_row); for the side of a three-column page, whose third column
        has ink on rows that are blank on this side."""
        if x0 == left and x1 == right:
            return in_row
        if (x0, x1) not in side_rows:
            side_rows[(x0, x1)] = area(x0, x1, 0, height - 1).any(axis=1).tolist()
        return side_rows[(x0, x1)]

    def gutter_of(
        y0: int, y1: int, x0: int = left, x1: int = right
    ) -> tuple[int, int] | None:
        """The gap between two columns in rows ``y0``-``y1``: a strip near
        the body's middle that long stretches of rows (a few lines at
        least) do not cross, holding the most ink between them. One column
        of text crosses any strip a few points wide on nearly every line
        (word spaces are narrower); a figure across the page breaks the
        stretches, not the columns beside it, and its own gaps do not
        count. None if there is none. Within ``x0``-``x1`` if given (the
        two columns on one side of a three-column page's first gap)."""
        across = x1 - x0 + 1
        rows = np.array(rows_in(x0, x1)[y0 : y1 + 1], dtype=bool)
        start = _round(x0 + across * 0.3)
        end = _round(x0 + across * 0.7)
        starts = end - start + 1 - GUTTER
        if starts <= 0:
            return None
        # A figure's own gaps (between its panels) are not columns: drawing
        # on both sides of the middle. (A figure in one column, text in the
        # other, does not hide their gap.)
        half = _round(x0 + across / 2)
        figures: dict[tuple[int, int], bool] = {}

        def figure(a: int, b: int) -> bool:
            if (a, b) not in figures:
                figures[(a, b)] = drawn(x0, half, a, b) and drawn(half + 1, x1, a, b)
            return figures[(a, b)]

        # Ink in each strip of GUTTER points, in each row.
        strip = np.zeros((y1 - y0 + 1, starts + GUTTER), dtype=np.int32)
        part = area(start, start + starts + GUTTER - 2, y0, y1)
        strip[: part.shape[0], 1 : part.shape[1] + 1] = part
        sums = strip.cumsum(axis=1)
        crossed = (sums[:, GUTTER : GUTTER + starts] - sums[:, :starts]) > 0
        inked = np.concatenate(([0], rows.cumsum()))
        # Per strip: ink rows in long uncrossed stretches.
        free = np.zeros(starts, dtype=np.int64)
        for g in range(starts):
            for a, b in runs(~crossed[:, g]):
                if b - a + 1 >= MIN_COLUMNS and not figure(y0 + a, y0 + b):
                    free[g] += inked[b + 1] - inked[a]
        # Enough of the page's text beside the gap (a page that is mostly
        # figure has little).
        text_rows = int(rows.sum())
        if text is not None:
            beside = text_ink[y0 : y1 + 1, max(0, x0) : x1 + 1].any(axis=1)
            text_rows = int((beside & rows).sum())
        most = int(free.max())
        if most < max(MIN_COLUMNS * 1.5, text_rows * 0.2):
            return None
        quiet = runs(free >= most * 0.9)
        middle = starts / 2
        a, b = min(quiet, key=lambda run: abs((run[0] + run[1]) / 2 - middle))
        return start + a, start + b + GUTTER - 1

    def dense(y: int) -> bool:
        """A row of a line of text (much ink across the body), not of an
        equation's limits or brackets."""
        return ink_across[y] > body_width * 0.2

    def edge_of(start: int, step: int, limit: int, rows: list[bool]) -> int | None:
        """From row ``start`` going ``step`` (up -1, down 1) no further than
        ``limit``: rows that belong with the part they touch rather than
        with what follows (closer to it than to the rest, a few lines at
        most): the last of them, else None."""

        def within(y: int) -> bool:
            return y >= limit if step < 0 else y <= limit

        y = start
        near = 0
        while within(y) and not rows[y]:
            near += 1
            y += step
        if not within(y) or near >= BLOCK_SPLIT:
            return None
        last = y
        far = 0
        # Rows without a line of text in them (an equation's limits and
        # brackets) go with it over less space.
        text_seen = False

        def apart() -> bool:
            return far >= (BLOCK_SPLIT if text_seen else 3)

        while within(y):
            if rows[y]:
                if apart():
                    break
                # The rows themselves a few lines at most (the space after
                # them may be wide).
                if abs(y - start) > MIN_COLUMNS:
                    return None
                if dense(y):
                    text_seen = True
                last = y
                far = 0
            else:
                far += 1
            y += step
        return last if apart() and far > near else None

    def filled(x0: int, x1: int, y0: int, y1: int, whole: bool = False) -> bool:
        """Lines (of text, or a figure) filling most of ``x0``-``x1``: a few
        at least in rows ``y0``-``y1``, as a column of text has. A line is a
        run of rows with much ink (lines of dense text touch; between them
        a row has little)."""
        part = area(x0, x1, y0, y1)
        counts = part.sum(axis=1)
        most = int(counts.max()) if counts.size else 0
        if not most:
            return False
        full = 0
        for a, b in runs(counts >= most * 0.3):
            columns = np.flatnonzero(part[a : b + 1].any(axis=0))
            # A rule, not a line: thin, or a few rows unbroken (text breaks
            # at every letter), as thick as it is drawn. (A shaded box
            # stands for a line, like a figure.)
            if b - a < 2 or (
                b - a < RULE_ROWS
                and longest(part[a + int(counts[a : b + 1].argmax())])
                >= (columns[-1] - columns[0]) * 0.5
            ):
                continue
            # Across most of the side; with ``whole``, without a wide gap
            # inside (an equation's "h.c." and its number, far apart, are
            # no line of text).
            widest = int(np.diff(columns).max()) - 1 if columns.size > 1 else 0
            if int(columns[-1] - columns[0]) >= (x1 - x0) * 0.55 and (
                not whole or widest <= LINE_GAP
            ):
                full += 1
            if full >= 3:
                return True
        return False

    def side_rule(y: int, a: int, b: int, closing: bool) -> bool:
        """Row ``y`` holds a rule across most of the side ``a``-``b`` with
        a tick at the gap: up at its right end (``closing``, the left side),
        else down at its left end."""
        for s, e in runs(ink[y], a, b):
            if e - s + 1 < (b - a + 1) * WIDE_RULE:
                continue
            if closing and b - e <= WIDE_RULE_GAP:
                beside, end = ink[max(0, y - WIDE_TICK) : y], e
            elif not closing and s - a <= WIDE_RULE_GAP:
                beside, end = ink[y + 1 : y + WIDE_TICK + 1], s
            else:
                continue
            # The tick, and nothing else along the rule (a table's double
            # rule is no tick).
            tick = beside[:, max(0, end - 1) : end + 2].any(axis=1)
            along = beside[:, s + 3 : e - 2].any()
            return bool(tick.all()) and not along
        return False

    def wide_spans(
        y0: int, y1: int, gutter: tuple[int, int], x0: int, x1: int
    ) -> list[tuple[int, int]]:
        """Rows set across the page between REVTeX's rules (``WIDE_RULE``):
        from a closing rule to the opening one below it, else to ``y1``
        (the equation goes on over the page); from ``y0`` to an opening
        rule without a closing one above (it came from the page before)."""
        gutter_left, gutter_right = gutter
        # The gap's middle blank (a rule may reach into its edge).
        inset = max(0, (gutter_right - gutter_left + 1 - 3) // 4)

        def gap_blank(y: int) -> bool:
            return not ink[y, gutter_left + inset : gutter_right - inset + 1].any()

        closing = [
            y
            for y in range(y0, y1 + 1)
            if side_rule(y, x0, gutter_left, True) and gap_blank(y)
        ]
        opening = [
            y
            for y in range(y0, y1 + 1)
            if side_rule(y, gutter_right, x1, False) and gap_blank(y)
        ]
        spans: list[tuple[int, int]] = []
        top = y0 if opening and (not closing or opening[0] < closing[0]) else None
        for row, closes in sorted(
            [(y, True) for y in closing] + [(y, False) for y in opening]
        ):
            if closes and top is None:
                top = row
            elif not closes and top is not None:
                spans.append((top, row))
                top = None
        if top is not None:
            spans.append((top, y1))
        return spans

    def bands_of(
        y0: int,
        y1: int,
        gutter: tuple[int, int],
        x0: int = left,
        x1: int = right,
        inside: bool = False,
    ) -> list[_Band]:
        """Rows ``y0``-``y1`` cut at the gap ``gutter`` into stretches
        across it (wide) and stretches in two columns. ``inside``: a gap
        found within a part across the page (beside an abstract, or before
        equations' numbers): lines of text whole only."""
        gutter_left, gutter_right = gutter
        rows = rows_in(x0, x1)
        # Rows crossing the gap are across the page. A few crossing rows
        # alone (a rule, an equation reaching over) are not; a crossing line
        # is whole, its accents and descenders with it.
        # The gap's middle half: a column's lines may reach into its edges
        # (justified to them, or hanging out at a reference's start).
        inset = max(0, (gutter_right - gutter_left + 1 - 3) // 4)
        gap_from, gap_to = gutter_left + inset, gutter_right - inset
        crosses = (
            np.array(rows[y0 : y1 + 1], dtype=bool)
            & area(gap_from, gap_to, y0, y1).any(axis=1)
        ).tolist()
        # A rule drawn across the gap (between the text and the references)
        # does end the columns above it: one unbroken line of ink over the
        # gap, a fifth of the width long at least, short of the whole width
        # (rules from edge to edge set off a title page's parts).
        middle = _round((gutter_left + gutter_right) / 2)

        def rule_at(y: int) -> bool:
            if not ink[y, middle]:
                return False
            a = b = middle
            while a > x0 and ink[y, a - 1]:
                a -= 1
            while b < x1 and ink[y, b + 1]:
                b += 1
            share = (b - a + 1) / (x1 - x0 + 1)
            return RULE_ACROSS <= share <= RULE_ACROSS_MOST

        for a, b in runs(crosses):
            # A gap still there beside what reaches into it from one side
            # (an equation's number at its column's edge): not across. (A
            # line across has letters either side of its word spaces.)
            inked = np.flatnonzero(
                area(gutter_left, gutter_right, y0 + a, y0 + b).any(axis=0)
            )
            blank = max(int(inked[0]), gutter_right - gutter_left - int(inked[-1]))
            if blank >= NARROW_GAP:
                crosses[a : b + 1] = [False] * (b - a + 1)
                continue
            if b - a + 1 >= 4:
                continue
            if not any(rule_at(y0 + i) for i in range(a, b + 1)):
                crosses[a : b + 1] = [False] * (b - a + 1)
        for top, bottom in wide_spans(y0, y1, gutter, x0, x1):
            crosses[top - y0 : bottom - y0 + 1] = [True] * (bottom - top + 1)
        last_row = len(crosses) - 1
        for a, b in runs(crosses):
            i = a - 1
            while i >= max(0, a - LINE_REACH) and rows[y0 + i]:
                crosses[i] = True
                i -= 1
            i = b + 1
            while i <= min(last_row, b + LINE_REACH) and rows[y0 + i]:
                crosses[i] = True
                i += 1
        bands: list[_Band] = []
        end = len(crosses) - 1
        i = 0
        while i <= end:
            wide = crosses[i]
            stop = i
            # A wide band runs on over short uncrossing stretches (a
            # figure's own gaps); a column band ends at the next crossing row.
            if wide:
                while stop < end:
                    after = stop + 1
                    while after <= end and not crosses[after]:
                        after += 1
                    if after > end or after - stop - 1 >= MIN_COLUMNS:
                        break
                    stop = after
            else:
                while stop < end and not crosses[stop + 1]:
                    stop += 1
            last = bands[-1] if bands else None
            short = stop - i + 1 < MIN_COLUMNS
            if (not wide and short and last) or (last and last.wide == (wide or short)):
                last.y1 = y0 + stop
            else:
                bands.append(_Band(y0 + i, y0 + stop, wide or short))
            i = stop + 1

        # Two "columns" of drawing are a figure's panels; two of a few
        # lines, or of lines short of the column (a title's words in large
        # type, equations and their numbers), are not columns either:
        # across the page.
        def display(a: int, b: int, band: _Band) -> bool:
            """Most text on a side in large type (a title's words either
            side of a gap found within a part across the page): no column.
            (Equations' symbols are large too, in the columns.)"""
            if sizes is None or not inside:
                return False
            # Line by line (a big title covers more of the side than its
            # lines' number).
            side = sizes[band.y0 : band.y1 + 1, max(0, a) : b + 1]
            lines = []
            for s, e in runs(side.max(axis=1) > 0):
                found = side[s : e + 1]
                lines.append(float(np.median(found[found > 0])))
            return bool(lines) and float(np.median(lines)) > large

        def two_lines(a: int, b: int, band: _Band) -> bool:
            """Lines of text (runs of rows with ink) on a side: two at
            least, not in large type."""
            inked = area(a, b, band.y0, band.y1).any(axis=1)
            lines = sum(1 for s, e in runs(inked) if e - s >= 3)
            return lines >= 2 and not display(a, b, band)

        def long_line(a: int, b: int, band: _Band) -> bool:
            """A line across most of a side (a figure's labels under it are
            short, however many rows of them)."""
            part = area(a, b, band.y0, band.y1)
            for s, e in runs(part.any(axis=1)):
                if e - s < 3:
                    continue
                inked = np.flatnonzero(part[s : e + 1].any(axis=0))
                if inked[-1] - inked[0] >= (b - a) * 0.6:
                    return True
            return False

        def clear(band: _Band) -> bool:
            """Nothing at all in the gap (not even a rule's or an equation's
            few rows)."""
            return not area(gap_from, gap_to, band.y0, band.y1).any()

        # Columns full of lines on both sides somewhere here: the page is set
        # in columns (else the looser test below does not apply: a
        # one-column page's figure labels may stand in two rows of short
        # lines). (Also with a figure in one of them, where nothing crosses
        # the gap: a figure at a column's top, its caption and text under it.)
        def full(band: _Band) -> bool:
            return (
                not band.wide
                and filled(x0, gutter_left - 1, band.y0, band.y1, inside)
                and filled(gutter_right + 1, x1, band.y0, band.y1, inside)
                and (not drawn(x0, x1, band.y0, band.y1) or clear(band))
                and not display(x0, gutter_left - 1, band)
                and not display(gutter_right + 1, x1, band)
            )

        def cells(a: int, b: int, band: _Band) -> bool:
            """A table's columns on a side: blank space down the band's
            whole height, in the side's middle (a list's gap after its
            numbers is at its edge; a column of text crosses any)."""
            inked = area(a, b, band.y0, band.y1).any(axis=0)
            across = b - a + 1
            return any(
                e - s + 1 >= TABLE_GAP and s >= across * 0.2 and e <= across * 0.8
                for s, e in runs(~inked)
            )

        # A table's two halves are no columns: across the page.
        for band in bands:
            if (
                not band.wide
                and cells(x0, gutter_left - 1, band)
                and cells(gutter_right + 1, x1, band)
            ):
                band.wide = True
        in_columns = any(full(band) for band in bands)
        for band in bands:
            if band.wide or full(band):
                continue
            if drawn(x0, x1, band.y0, band.y1):
                band.wide = True
                continue
            # One side full of lines here (the other mostly an equation)
            # says columns as well as full ones elsewhere on the page.
            one_full = filled(x0, gutter_left - 1, band.y0, band.y1, inside) or filled(
                gutter_right + 1, x1, band.y0, band.y1, inside
            )
            # Columns with few full lines (one mostly equations, the
            # references' first lines at a page's foot, a column's last two
            # lines beside the other's equations) are columns still where the
            # gap between them is clear, in the middle (not the gap before
            # equations' numbers), both sides have two lines at least,
            # neither is a drawing (a figure beside the text), they go on for
            # a few lines, and the page is set in columns (full ones
            # elsewhere, or one side full here).
            tall = band.y1 - band.y0 + 1 >= MIN_COLUMNS
            centred = (
                abs((gutter_left + gutter_right) / 2 - (x0 + x1) / 2)
                <= (x1 - x0 + 1) * 0.1
            )
            if (
                (in_columns or one_full)
                and tall
                and centred
                and clear(band)
                and two_lines(x0, gutter_left - 1, band)
                and two_lines(gutter_right + 1, x1, band)
                and (
                    long_line(x0, gutter_left - 1, band)
                    or long_line(gutter_right + 1, x1, band)
                )
                # (an equation's bars and roots are a little drawing; a
                # figure is more)
                and not drawn(x0, gutter_left - 1, band.y0, band.y1, 0.3)
                and not drawn(gutter_right + 1, x1, band.y0, band.y1, 0.3)
            ):
                continue
            band.wide = True
        merged: list[_Band] = []
        for band in bands:
            if merged and merged[-1].wide == band.wide:
                merged[-1].y1 = band.y1
            else:
                merged.append(_Band(band.y0, band.y1, band.wide))

        # A figure keeps the drawn rows next to it (its top panels standing
        # either side of the columns' gap), up to the first line of text.
        def sketch(y: int) -> bool:
            return rows[y] and drawn(x0, x1, y, y)

        for i, band in enumerate(merged):
            if not band.wide or not drawn(x0, x1, band.y0, band.y1):
                continue
            above = merged[i - 1] if i else None
            if above and not above.wide:
                y = band.y0 - 1
                while y > above.y0 and (sketch(y) or (not rows[y] and sketch(y - 1))):
                    y -= 1
                if y < band.y0 - 1:
                    band.y0, above.y1 = y + 1, y
            below = merged[i + 1] if i + 1 < len(merged) else None
            if below and not below.wide:
                y = band.y1 + 1
                while y < below.y1 and (sketch(y) or (not rows[y] and sketch(y + 1))):
                    y += 1
                if y > band.y1 + 1:
                    band.y1, below.y0 = y - 1, y
        # A part across the page keeps what touches it above and below (a
        # figure's labels, an axis, the short last line of a caption or of
        # the authors), if that is closer to it than to the columns.
        for i, band in enumerate(merged):
            if not band.wide:
                continue
            above = merged[i - 1] if i else None
            if above and not above.wide:
                edge = edge_of(band.y0 - 1, -1, above.y0, rows)
                if edge is not None:
                    band.y0 = edge
                    above.y1 = edge - 1
            below = merged[i + 1] if i + 1 < len(merged) else None
            if below and not below.wide:
                edge = edge_of(band.y1 + 1, 1, below.y1, rows)
                if edge is not None:
                    band.y1 = edge
                    below.y0 = edge + 1
        # Stretched bands may have reached into each other: none overlaps.
        last_y = y0 - 1
        kept: list[_Band] = []
        for band in merged:
            band.y0 = max(band.y0, last_y + 1)
            if band.y1 < band.y0:
                continue
            last_y = band.y1
            kept.append(band)
        return kept

    # The page's two columns run on over any blank space. A part across them
    # may have columns of its own (a box beside the abstract above the
    # body's columns); else it is cut into blocks at blank space, each
    # keeping only its own ink: an abstract narrower than the page fills
    # the screen too. A figure's blocks (its panels) stay together.
    found: list[_Box] = []
    main_span = 0

    def side_parts(side: _Box, band: _Band) -> list[_Box]:
        """One side of a page's columns gap: a column, or (wider than half
        the body: two of three columns) its own stretches, in two columns
        where it has them, across the side where not."""
        column = [_Box(side.x0, side.x1, side.y0, side.y1)]
        if side.x1 - side.x0 + 1 < body_width * THIRD_COLUMN_SIDE:
            return column
        own = gutter_of(band.y0, band.y1, side.x0, side.x1)
        if own is None:
            return column
        parts: list[_Box] = []
        for sub in bands_of(band.y0, band.y1, own, side.x0, side.x1):
            a = None if sub.wide else extent(side.x0, own[0] - 1, sub.y0, sub.y1)
            b = None if sub.wide else extent(own[1] + 1, side.x1, sub.y0, sub.y1)
            if a and b:
                parts += [a, b]
            else:
                whole = extent(side.x0, side.x1, sub.y0, sub.y1)
                if whole:
                    whole.wide = True
                    parts.append(whole)
        return parts if any(not part.wide for part in parts) else column

    def place(y0: int, y1: int, gutter: tuple[int, int] | None, main: bool) -> None:
        nonlocal main_span
        bands = (
            bands_of(y0, y1, gutter, left, right, not main)
            if gutter
            else [_Band(y0, y1, True)]
        )
        for band in bands:
            if not band.wide and gutter:
                one = extent(left, gutter[0] - 1, band.y0, band.y1)
                two = extent(gutter[1] + 1, right, band.y0, band.y1)
                if one and two:
                    # Three columns: the gap nearest the middle leaves two on
                    # one side; that side has its own gap, and its own
                    # stretches across it (a title and abstract over two of
                    # the columns).
                    parts = side_parts(one, band) + side_parts(two, band)
                    # All columns as wide as the widest: their text alike.
                    widest = max(p.x1 - p.x0 for p in parts if not p.wide) + 1
                    if main:
                        main_span = max(main_span, widest)
                    for part in parts:
                        if not part.wide:
                            part.span = widest
                        found.append(part)
                    continue
            if main and not drawn(left, right, band.y0, band.y1):
                own = gutter_of(band.y0, band.y1)
                if own and (not gutter or own[1] < gutter[0] or own[0] > gutter[1]):
                    place(band.y0, band.y1, own, False)
                    continue
            blocks: list[Run] = []
            for block in joined(runs(in_row, band.y0, band.y1), block_split):
                if (
                    blocks
                    and block[0] - blocks[-1][1] - 1 < FIGURE_GAP
                    and (
                        drawn(left, right, blocks[-1][0], blocks[-1][1])
                        or drawn(left, right, block[0], block[1])
                    )
                ):
                    blocks[-1][1] = block[1]
                else:
                    blocks.append(block)
            for b0, b1 in blocks:
                # A rule alone (a few rows) is no piece: the view draws its
                # own line between pieces.
                if b1 - b0 + 1 < 4:
                    continue
                whole = extent(left, right, b0, b1)
                if whole:
                    whole.wide = True
                    found.append(whole)

    place(top, bottom, gutter_of(top, bottom), True)

    # A column running on below the end of a part across the others (the
    # third column beside a title over the first two, Science's): one
    # piece, read where its lower part is, as wide as the columns there.
    kept: list[_Box] = []
    for i, f in enumerate(found):
        below = next(
            (
                g
                for g in found[i + 1 :]
                if not f.wide
                and not g.wide
                and abs(g.x0 - f.x0) <= SIDE_GAP / 2
                and abs(g.x1 - f.x1) <= SIDE_GAP / 2
                and 0 <= g.y0 - f.y1 <= BLOCK_SPLIT
            ),
            None,
        )
        if below is None:
            kept.append(f)
        else:
            below.x0, below.x1 = min(f.x0, below.x0), max(f.x1, below.x1)
            below.y0 = f.y0
    found[:] = kept

    # Two columns over a good part of the page, not just a figure with its
    # caption beside it. A part across the page is never shown larger than
    # the columns' text (else the body's).
    in_columns = sum(f.y1 - f.y0 + 1 for f in found if not f.wide) / 2
    columns = in_columns >= (bottom - top + 1) * 0.3
    most = main_span or max([0] + [f.span for f in found if not f.wide]) or body_width
    pieces: list[Piece] = []
    for f in found:
        x = max(leftmost, f.x0 - pad)
        y = max(0, f.y0 - pad)
        pieces.append(
            {
                "x": x,
                "y": y,
                "width": min(rightmost, f.x1 + pad + 1) - x,
                "height": min(height, f.y1 + pad + 1) - y,
                "wide": f.wide,
                "span": (max(f.x1 - f.x0 + 1, most) if f.wide else f.span) + 2 * pad,
            }
        )
    return columns, pieces


def analyse(page: pypdfium2.PdfPage, first: bool) -> PageLayout:
    """A page's layout: drawn at one pixel a point, where it has ink and
    where text."""
    width, height = page.get_size()
    bitmap = page.render(scale=1, grayscale=True, may_draw_forms=False)
    try:
        pixels = np.frombuffer(bytes(bitmap.buffer), dtype=np.uint8).reshape(
            bitmap.height, bitmap.stride
        )[:, : bitmap.width]
        ink = pixels < INK_LIGHT
    finally:
        bitmap.close()
    text, turned = _text_boxes(page, bitmap.width, bitmap.height)
    # Turned text (a download line running up the margin, arXiv's stamp) is
    # no part of the page's reading: its ink goes, however close it sits.
    for x0, y0, x1, y1 in turned:
        ink[y0 : y1 + 1, x0 : x1 + 1] = False
    columns, pieces = lay_out(ink, first, text)
    return {"width": width, "height": height, "columns": columns, "pieces": pieces}


def _text_boxes(
    page: pypdfium2.PdfPage, width: int, height: int
) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """Where a page has text (its characters' boxes, one pixel a point),
    each pixel its type size (points; 0 where none): ink outside them is
    drawn (figures). ``turned``: the boxes of text set upright (x0, y0,
    x1, y1)."""
    boxes = np.zeros((height, width), dtype=np.float32)
    turned: list[tuple[int, int, int, int]] = []
    # From the page's points to the picture's pixels (its rotation and crop
    # box with it).
    device = _device_transform(page, width, height)
    textpage = page.get_textpage()
    try:
        for i in range(textpage.count_chars()):
            char = textpage.get_text_range(i, 1)
            if not char.strip():
                continue
            left, bottom, right, top = textpage.get_charbox(i, loose=True)
            if right <= left or top <= bottom:
                continue
            xs, ys = zip(
                *(device(x, y) for x in (left, right) for y in (bottom, top)),
                strict=True,
            )
            angle = pdfium_c.FPDFText_GetCharAngle(textpage.raw, i)
            if angle >= 0 and abs(math.sin(angle)) > abs(math.cos(angle)):
                turned.append(
                    (
                        max(0, math.floor(min(xs)) - 1),
                        max(0, math.floor(min(ys)) - 1),
                        min(width - 1, math.ceil(max(xs)) + 1),
                        min(height - 1, math.ceil(max(ys)) + 1),
                    )
                )
                continue
            x0, x1 = max(0, math.floor(min(xs))), min(width - 1, math.ceil(max(xs)))
            y0, y1 = max(0, math.floor(min(ys))), min(height - 1, math.ceil(max(ys)))
            boxes[y0 : y1 + 1, x0 : x1 + 1] = top - bottom
    finally:
        textpage.close()
    return boxes, turned


def _device_transform(page: pypdfium2.PdfPage, width: int, height: int) -> Any:  # noqa: ANN401 (a function of two floats)
    """Page points to pixels, as PDFium draws the page: from three points
    far apart (PDFium gives whole pixels)."""
    far = 10_000.0

    def to_device(x: float, y: float) -> tuple[float, float]:
        dx, dy = ctypes.c_int(), ctypes.c_int()
        pdfium_c.FPDF_PageToDevice(
            page.raw, 0, 0, width * 100, height * 100, 0, x, y, dx, dy
        )
        return dx.value / 100, dy.value / 100

    ox, oy = to_device(0, 0)
    ax, ay = to_device(far, 0)
    bx, by = to_device(0, far)
    a, b = (ax - ox) / far, (ay - oy) / far
    c, d = (bx - ox) / far, (by - oy) / far

    def device(x: float, y: float) -> tuple[float, float]:
        return ox + a * x + c * y, oy + b * x + d * y

    return device
