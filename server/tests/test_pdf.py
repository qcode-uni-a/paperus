"""PDFium in helper processes: damaged PDFs, and helpers that hang, die or
run out of memory, each ending as a ``PdfError`` the next PDF does not
notice."""

import os
import time
from pathlib import Path

import pytest

from paperus import pdf
from tests.pdfs import make_pdf

GOOD = make_pdf([["Radar gaps"]], title="Radar")


# Run in a helper process instead of reading a PDF:


def _hang(path: str) -> None:
    time.sleep(60)


def _die(path: str) -> None:
    os._exit(1)


def _run_out_of_memory(path: str) -> None:
    raise MemoryError


@pytest.fixture
def new_helpers() -> None:
    """The helpers so far end normally first (and save their coverage):
    the test's breaking ones are ended by force."""
    if pdf._pool is not None:
        pdf._pool.shutdown()
        pdf._pool = None


@pytest.fixture
def good(tmp_path: Path) -> Path:
    path = tmp_path / "good.pdf"
    path.write_bytes(GOOD)
    return path


def test_reading(good: Path) -> None:
    assert [page.strip() for page in pdf.pages(good)] == ["Radar gaps"]
    assert pdf.title(good) == "Radar"
    assert pdf.render(good, 0).startswith(b"\x89PNG")


def test_damaged_pdfs(good: Path, tmp_path: Path) -> None:
    # The document opens, but its page does not.
    damaged = tmp_path / "damaged.pdf"
    damaged.write_bytes(GOOD.replace(b"/Type /Page /Parent", b"/Type /Pagx /Parent"))
    with pytest.raises(pdf.PdfError, match="PdfiumError: Failed to load page"):
        pdf.pages(damaged)
    with pytest.raises(pdf.PdfError, match="PdfiumError"):
        pdf.render(good, 5)
    garbage = tmp_path / "garbage.pdf"
    garbage.write_bytes(b"%PDF-1.7 and then nothing")
    with pytest.raises(pdf.PdfError, match="PdfiumError"):
        pdf.title(garbage)


def test_a_helper_that_hangs(
    new_helpers: None, good: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(pdf, "SECONDS", 0.5)
        with pytest.raises(pdf.PdfError, match=r"longer than 0\.5 seconds"):
            pdf._run(_hang, good)
    assert pdf.title(good) == "Radar"  # with new helpers


def test_a_helper_that_dies(new_helpers: None, good: Path) -> None:
    with pytest.raises(pdf.PdfError, match="made its reader stop"):
        pdf._run(_die, good)
    assert pdf.title(good) == "Radar"


def test_a_helper_out_of_memory(good: Path) -> None:
    with pytest.raises(pdf.PdfError, match="too much memory"):
        pdf._run(_run_out_of_memory, good)
    assert pdf.title(good) == "Radar"
