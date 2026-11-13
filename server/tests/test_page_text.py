"""A PDF's text read by its page layouts (``page_layout.read``): in reading
order across columns and pages, without running headers, page numbers and
figures' labels, captions apart (issue #43). Tested on a paper written here
(the layout twins have no text)."""

from pathlib import Path

import pypdfium2

from paperus import page_layout, pdf, processing
from tests.pdfs import Box, Text, make_placed_pdf

LEFT, RIGHT, SIZE, PITCH = 72, 324, 9, 12
# Words of the body, in reading order ("Ab1 Abc2 Abcd3 …": of many lengths, so
# that their spaces do not line up), a sentence of ten; four on a line.
PER_LINE = 4


def body(start: int, lines: int) -> list[str]:
    words = [
        "Abcde"[: 1 + n % 5] + str(n) + ("." if n % 10 == 0 else "")
        for n in range(start, start + lines * PER_LINE)
    ]
    return [" ".join(words[i : i + PER_LINE]) for i in range(0, len(words), PER_LINE)]


def column(x: float, top: float, lines: list[str]) -> list[Text]:
    return [(x, top + i * PITCH, SIZE, line) for i, line in enumerate(lines)]


def page(
    number: int, texts: list[Text], boxes: list[Box]
) -> tuple[list[Text], list[Box]]:
    """A page with its number under the text and, after the first, a
    running header."""
    header = [(LEFT, 40, 8, f"Journal of Tests 1 (2026) {number}-2")]
    folio = (300, 740, 8, str(number))
    return [*header[: number - 1], *texts, folio], boxes


def paper() -> bytes:
    """Two pages in two columns; in the first page's right column a figure
    (a frame and markers, labels in it) and its caption; a word broken
    over the page."""
    left = body(1, 50)
    above = body(201, 16)
    below = body(265, 20)
    # The first page's last word broken: "hyphen-" … "ated" (for 344, 345).
    below[-1] = below[-1].rsplit(" ", 1)[0] + " hyphen-"
    after = body(345, 50)
    after[0] = "ated " + after[0].split(" ", 1)[1]
    figure: list[Box] = [(RIGHT, 300, 216, 110, False)] + [
        (RIGHT + 12 + 13 * k, 400 - 6 * k, 5, 5, True) for k in range(16)
    ]
    labels: list[Text] = [(RIGHT + 4, 304, 7, "1.0"), (RIGHT + 4, 398, 7, "0.5")]
    caption = column(RIGHT, 418, ["FIG. 1. A figure of tests,", "its caption."])
    first = page(
        1,
        column(LEFT, 100, left)
        + column(RIGHT, 100, above)
        + labels
        + [(x, y, 8, t) for x, y, _, t in caption]
        + column(RIGHT, 460, below),
        figure,
    )
    second = page(
        2,
        column(LEFT, 100, after) + column(RIGHT, 100, body(545, 50)),
        [],
    )
    return make_placed_pdf([first, second])


def expected() -> list[str]:
    words = " ".join(body(1, 50) + body(201, 16) + body(265, 20)).split()[:-1]
    words += ["hyphenated", *" ".join(body(345, 50) + body(545, 50)).split()[1:]]
    return words


def test_pieces_in_reading_order_without_header_and_labels(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(paper())
    with pypdfium2.PdfDocument(path) as document:
        layout, parts = page_layout.read(document[0], True)
    assert layout["columns"]
    [drawing] = layout["figures"]
    assert abs(drawing["x"] - RIGHT) <= 3 and drawing["width"] >= 200
    text = [t for t, caption in parts if not caption]
    assert [t for t, caption in parts if caption] == [
        "FIG. 1. A figure of tests,\nits caption."
    ]
    joined = "\n".join(text)
    assert "Journal" not in joined and "1.0" not in joined and "0.5" not in joined
    assert joined.split()[0] == "Ab1" and joined.split()[-1].startswith("hyphen")


def test_passages_flow_across_columns_and_pages(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(paper())
    read = pdf.read(path)
    assert read.layouts is not None and read.pieces is not None
    chunks = processing._pages_text(read.pages, read.pieces, {}).chunks
    assert chunks is not None
    captions = [c for c in chunks if c.text.startswith("FIG.")]
    assert [(c.text, c.page) for c in captions] == [
        ("FIG. 1. A figure of tests, its caption.", 1)
    ]
    flow = [c for c in chunks if c not in captions]
    assert " ".join(c.text for c in flow).split() == expected()
    # Each passage from the page it starts on; sentences whole.
    assert flow[0].page == 1 and flow[-1].page == 2
    assert all(c.text.endswith(".") for c in flow[:-1])
    on_two = next(c for c in flow if "hyphenated" in c.text)
    assert on_two.page == 1
