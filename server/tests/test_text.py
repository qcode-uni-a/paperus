from pathlib import Path

import pytest

from paperus import pdf
from paperus.text import (
    MAX_WORDS,
    TARGET_WORDS,
    Flow,
    chunk_document,
    chunk_flow,
    chunk_pages,
    chunk_text,
    extract_pdf_pages,
    heading,
    html_text,
)
from tests.pdfs import make_pdf


def words(n: int, word: str = "word") -> str:
    return " ".join([word] * n)


def test_short_paragraphs_are_merged() -> None:
    chunks = chunk_text("First paragraph.\n\nSecond paragraph.", page=3)
    assert [c.text for c in chunks] == ["First paragraph.\n\nSecond paragraph."]
    assert chunks[0].page == 3


def test_paragraphs_start_new_chunks_near_the_target() -> None:
    text = f"{words(150, 'a')}.\n\n{words(150, 'b')}."
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert chunks[0].text.startswith("a ") and chunks[1].text.startswith("b ")


def test_long_paragraphs_split_at_sentences() -> None:
    sentence = f"{words(49, 'x').capitalize()} end."
    chunks = chunk_text(" ".join([sentence] * 10))
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text.split()) <= TARGET_WORDS
        assert chunk.text.endswith("end.")


def test_endless_sentences_are_cut() -> None:
    chunks = chunk_text(words(MAX_WORDS * 2 + 10))
    assert [len(c.text.split()) for c in chunks] == [MAX_WORDS, MAX_WORDS, 10]


def test_cleanup() -> None:
    [chunk] = chunk_text("Hydro-\nlogy of   rivers\r\nand lakes")
    assert chunk.text == "Hydrology of rivers and lakes"
    # As PDFium reads a LaTeX PDF's hyphenation; and a soft hyphen.
    [chunk] = chunk_text("a co\u0002\r\nherent state, den\u00adsities")
    assert chunk.text == "a coherent state, densities"


def test_chunk_pages_keeps_page_numbers() -> None:
    chunks = chunk_pages(["one", "", "three"])
    assert [(c.text, c.page) for c in chunks] == [("one", 1), ("three", 3)]


def test_extract_pdf_pages(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf([["Hello (world)", "next line"], []]))
    pages = extract_pdf_pages(path)
    assert len(pages) == 2
    assert "Hello (world)" in pages[0] and "next line" in pages[0]
    assert pages[1] == ""


def test_reference_list_is_marked() -> None:
    pages = [
        "Introduction\n\nDroughts are measured with indices.",
        "Results follow.\n7 References\n"
        "[1] A. Huber, Drought indices, 2024.\n[2] B. Ko, Rivers.",
        "[3] C. Li, Lakes, 2020.\nAppendix A. Extra results\n\nMore body text.",
    ]
    chunks = chunk_pages(pages)
    marked = [(c.page, c.references, c.text.split()[0]) for c in chunks]
    assert marked == [
        (1, False, "Introduction"),
        (2, False, "Results"),
        (2, True, "7"),
        (3, True, "[3]"),
        (3, False, "Appendix"),
    ]


def test_reference_headings() -> None:
    for title in [
        "REFERENCES",
        "Bibliography",
        "Literaturverzeichnis",
        "IV. References",
        "## References",
    ]:
        [body, refs] = chunk_document(f"Body text.\n{title}\nSmith (2020).")
        assert (body.references, refs.references) == (False, True), title
    # A sentence mentioning references is not a heading.
    [chunk] = chunk_document("The references below were checked.\nSmith (2020).")
    assert not chunk.references


def test_the_flow_runs_on_across_pieces_and_pages() -> None:
    """Pieces in reading order are one text: a sentence over a column's or
    a page's end stays whole, a word broken there is one again; a passage
    has the page it starts on."""
    parts: list[tuple[str, int, Flow]] = [
        ("A sentence that starts in the left column and", 1, "text"),
        ("ends in the right one. Then a hyphen\u0002", 1, "text"),
        ("ated word, a word broken by a hyphen-", 2, "text"),
        ("ated by hand, and Rabi-", 2, "text"),
        ("Bloch.", 2, "text"),
    ]
    [chunk] = chunk_flow(parts)
    assert chunk.page == 1
    assert chunk.text == (
        "A sentence that starts in the left column and ends in the right one."
        " Then a hyphenated word, a word broken by a hyphenated by hand, and"
        " Rabi-Bloch."
    )
    long: list[tuple[str, int, Flow]] = [
        (f"{words(120, 'A')}.", 1, "text"),
        (f"{words(120, 'B')}.", 2, "text"),
    ]
    assert [(c.page, c.text[0]) for c in chunk_flow(long)] == [(1, "A"), (2, "B")]
    # Endless sentences are cut; words longer than any are left out.
    endless = chunk_flow([(f"{words(MAX_WORDS + 10)} {'x' * 300}", 1, "text")])
    assert [len(c.text.split()) for c in endless] == [MAX_WORDS, 10]


def test_headings_start_passages() -> None:
    """At a section's heading (after a few words: no passage of a title
    alone; a heading right under another goes with it)."""
    text = words(30, "text") + "."
    parts: list[tuple[str, int, Flow]] = [
        ("Title of the paper\nAbstract\n" + text, 1, "text"),
        ("I. INTRODUCTION\nA. Earlier work\n" + text, 1, "text"),
        ("2.1 Methods and data\n" + text + "\nConclusions\nIt works.", 2, "text"),
    ]
    starts = [(c.page, " ".join(c.text.split()[:4])) for c in chunk_flow(parts)]
    assert starts == [
        (1, "Title of the paper"),
        (1, "I. INTRODUCTION A. Earlier"),
        (2, "2.1 Methods and data"),
        (2, "Conclusions It works."),
    ]
    for line in ["IV. RESULTS", "3 Results and discussion", "Acknowledgments"]:
        assert heading(line), line
    for line in ["3 K, the sample", "1 2 3 4", "We study things.", "Table 1 0.5 0.7"]:
        assert not heading(line), line


def test_captions_and_pages_alone() -> None:
    """A caption is a passage of its own, the flow running on past it; a
    page without layout (read by OCR) is a section of its own."""
    parts: list[tuple[str, int, Flow]] = [
        ("The text before the figure", 1, "text"),
        ("FIG. 1. A figure.", 1, "caption"),
        ("goes on after it.", 1, "text"),
        ("A scanned page.", 2, "page"),
        ("More text.", 3, "text"),
    ]
    chunks = chunk_flow(parts)
    assert [(c.page, c.text) for c in chunks] == [
        (1, "The text before the figure goes on after it."),
        (1, "FIG. 1. A figure."),
        (2, "A scanned page."),
        (3, "More text."),
    ]
    assert [c.caption for c in chunks] == [False, True, False, False]


def test_a_reference_list_in_the_flow() -> None:
    """Its heading counts where entries follow: not on a contents page."""
    text = words(30, "text") + "."
    parts: list[tuple[str, int, Flow]] = [
        ("Contents\nReferences\n1. Introduction\n2. Methods", 1, "text"),
        ("1 Introduction\n" + text, 2, "text"),
        (
            "References\n[1] A. Huber, Drought, 2024.\n[2] B. Ko, Rivers, 2020.",
            3,
            "text",
        ),
        ("FIG. 9. Kept with the list.", 3, "caption"),
        ("Appendix A. More\nBody again.", 4, "text"),
    ]
    marked = [(c.page, c.references, c.text.split()[0]) for c in chunk_flow(parts)]
    assert marked == [
        (1, False, "Contents"),
        (3, True, "References"),
        (3, True, "FIG."),
        (4, False, "Appendix"),
    ]
    long_entries = (
        "References\n[1] Anna Bee, Carl Dee,\nEva Fee, and others,\nJ. Tests 1"
    )
    assert chunk_flow([(long_entries, 1, "text")])[0].references
    authors = "References\n1. Yoneda, J. et al.\nA spin qubit."
    assert chunk_flow([(authors, 1, "text")])[0].references


def test_pdfs_are_read_in_helper_processes(tmp_path: Path) -> None:
    """PDFium runs in helper processes; a damaged PDF gives a message."""
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_pdf([["Radar gaps"], ["Second page"]]))
    assert [p.strip() for p in pdf.pages(path)] == ["Radar gaps", "Second page"]
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7 this is no PDF")
    with pytest.raises(pdf.PdfError, match="Data format error"):
        pdf.pages(broken)
    # The helpers still work after that.
    assert pdf.pages(path)[0].strip() == "Radar gaps"


def test_web_pages_give_their_readable_text() -> None:
    """Snapshots (e.g. from Zotero): no markup, scripts or embedded images."""
    image = "data:image/png;base64," + "A" * 5000
    page = f"""<html><head><title>Phys. Rev. B</title>
    <style>p {{ color: red }}</style></head>
    <body><script>var tracker = 1;</script>
    <h1>Path-integral simulation of exchange</h1>
    <p>We simulate the <b>exchange</b> interaction.</p><img src="{image}">
    <p>{image} Holes in germanium.</p></body></html>""".encode()
    readable = html_text(page)
    assert "tracker" not in readable and "color" not in readable
    [chunk] = chunk_document(readable)
    assert chunk.text == (
        "Path-integral simulation of exchange\n\n"
        "We simulate the exchange interaction.\n\nHoles in germanium."
    )
