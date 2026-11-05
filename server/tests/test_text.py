import threading
import time
from pathlib import Path

import pytest

from paperus import text
from paperus.text import (
    MAX_WORDS,
    TARGET_WORDS,
    chunk_document,
    chunk_pages,
    chunk_text,
    extract_pdf_pages,
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
    for heading in [
        "REFERENCES",
        "Bibliography",
        "Literaturverzeichnis",
        "IV. References",
        "## References",
    ]:
        [body, refs] = chunk_document(f"Body text.\n{heading}\nSmith (2020).")
        assert (body.references, refs.references) == (False, True), heading
    # A sentence mentioning references is not a heading.
    [chunk] = chunk_document("The references below were checked.\nSmith (2020).")
    assert not chunk.references


def test_one_thread_at_a_time_in_pdfium(monkeypatch: pytest.MonkeyPatch) -> None:
    """PDFium is not thread-safe: reading in parallel threads takes turns."""
    inside = 0
    most = 0
    guard = threading.Lock()

    def slow_read(path: Path) -> list[str]:
        nonlocal inside, most
        with guard:
            inside += 1
            most = max(most, inside)
        time.sleep(0.05)
        with guard:
            inside -= 1
        return []

    monkeypatch.setattr(text, "_pdf_pages", slow_read)
    threads = [
        threading.Thread(target=text.extract_pdf_pages, args=(Path("x.pdf"),))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert most == 1


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
