"""PDFium in helper processes.

PDFium is not thread-safe, and the worker reads several files at once: two
PDFs read in two threads once grew the worker to 15 GB until it was killed,
and made hundreds of valid PDFs fail. Here each PDF is read in a small
helper process of its own: in parallel for real, with a memory limit and a
time limit, and a broken PDF can at worst end its own helper.
"""

import contextlib
import logging
import os
import resource
import threading
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from pathlib import Path

import pypdfium2

log = logging.getLogger(__name__)

# Helpers at most; how many files are read at once is the worker's setting.
PROCESSES = max(1, min(8, (os.cpu_count() or 2) // 2))
# Memory one helper may use, and how long one PDF may take.
MEMORY_BYTES = 3 * 1024**3
SECONDS = 300
# A helper is replaced after this many PDFs, so leaks cannot add up.
TASKS_PER_HELPER = 50


class PdfError(Exception):
    """The PDF could not be read (damaged, too large, too slow)."""


_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()


def _limit_memory() -> None:
    # Where not allowed (some containers), the helper goes without.
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(
                max_workers=PROCESSES,
                # Not forked from the threaded worker: a fresh interpreter.
                mp_context=get_context("spawn"),
                initializer=_limit_memory,
                max_tasks_per_child=TASKS_PER_HELPER,
            )
        return _pool


def _reset(pool: ProcessPoolExecutor) -> None:
    """End a pool whose helper hangs or died; the next call starts anew."""
    global _pool
    with _pool_lock:
        if _pool is pool:
            _pool = None
    for process in list(getattr(pool, "_processes", {}).values()):
        process.terminate()
    pool.shutdown(wait=False, cancel_futures=True)


def _run[T](function: Callable[[str], T], path: Path) -> T:
    pool = _get_pool()
    future = pool.submit(function, str(path))
    try:
        return future.result(timeout=SECONDS)
    except TimeoutError as error:
        _reset(pool)
        raise PdfError(f"reading took longer than {SECONDS} seconds") from error
    except BrokenProcessPool as error:
        _reset(pool)
        raise PdfError("the PDF made its reader stop (too large or damaged)") from error
    except MemoryError as error:
        raise PdfError("the PDF needs too much memory") from error


def pages(path: Path) -> list[str]:
    """The text of each page; empty strings for pages without text."""
    return _run(_pages, path)


def title(path: Path) -> str | None:
    """The title the PDF's own metadata gives, if any."""
    return _run(_title, path)


# In the helper process:


def _open(path: str) -> pypdfium2.PdfDocument:
    try:
        return pypdfium2.PdfDocument(path)
    except pypdfium2.PdfiumError as error:
        # As a plain message: PDFium's own errors do not travel between
        # processes intact.
        raise PdfError(f"PdfiumError: {error}") from None


def _pages(path: str) -> list[str]:
    pdf = _open(path)
    try:
        found = []
        for index in range(len(pdf)):
            try:
                page = pdf[index]
                text_page = page.get_textpage()
            except pypdfium2.PdfiumError as error:
                raise PdfError(f"PdfiumError: {error}") from None
            found.append(text_page.get_text_bounded())
            text_page.close()
            page.close()
        return found
    finally:
        pdf.close()


def _title(path: str) -> str | None:
    pdf = _open(path)
    try:
        value = pdf.get_metadata_dict().get("Title")
    finally:
        pdf.close()
    return value or None
