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
import struct
import threading
import zlib
from collections.abc import Callable, Generator
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
# Pages for OCR: at this resolution, and at most this many pixels on the
# longer side (posters).
OCR_DPI = 200
OCR_MAX_SIDE = 4000


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


def _run[T](function: Callable[..., T], path: Path, *args: object) -> T:
    pool = _get_pool()
    future = pool.submit(function, str(path), *args)
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


def render(path: Path, index: int) -> bytes:
    """Page ``index`` (from 0) as a greyscale PNG, for OCR."""
    return _run(_render, path, index)


def png(width: int, height: int, pixels: bytes, stride: int) -> bytes:
    """An 8-bit greyscale PNG of rows of pixels (``stride`` bytes apart)."""
    rows = b"".join(
        b"\0" + pixels[y * stride : y * stride + width] for y in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )


# In the helper process:


@contextlib.contextmanager
def _open(path: str) -> Generator[pypdfium2.PdfDocument]:
    """The PDF, closed afterwards; PDFium's errors as ``PdfError``, with a
    plain message (its own errors do not travel between processes intact)."""
    try:
        pdf = pypdfium2.PdfDocument(path)
        try:
            yield pdf
        finally:
            pdf.close()
    except pypdfium2.PdfiumError as error:
        raise PdfError(f"PdfiumError: {error}") from None


def _pages(path: str) -> list[str]:
    found = []
    with _open(path) as pdf:
        for index in range(len(pdf)):
            page = pdf[index]
            text_page = page.get_textpage()
            found.append(text_page.get_text_bounded())
            text_page.close()
            page.close()
    return found


def _title(path: str) -> str | None:
    with _open(path) as pdf:
        return pdf.get_metadata_dict().get("Title") or None


def _render(path: str, index: int) -> bytes:
    with _open(path) as pdf:
        page = pdf[index]
        width, height = page.get_size()
        scale = min(OCR_DPI / 72, OCR_MAX_SIDE / max(width, height, 1))
        bitmap = page.render(scale=scale, grayscale=True)
        image = png(bitmap.width, bitmap.height, bytes(bitmap.buffer), bitmap.stride)
        bitmap.close()
        page.close()
        return image
