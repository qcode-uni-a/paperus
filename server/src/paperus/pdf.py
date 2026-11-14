"""PDFium in helper processes.

PDFium is not thread-safe, and the worker reads several files at once: two
PDFs read in two threads once grew the worker to 15 GB until it was killed,
and made hundreds of valid PDFs fail. Here each PDF is read in a small
helper process of its own: in parallel for real, with a memory limit and a
time limit, and a broken PDF can at worst end its own helper.
"""

import contextlib
import ctypes
import logging
import os
import re
import struct
import sys
import threading
import zlib
from collections.abc import Callable, Generator
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import pypdfium2
import pypdfium2.raw as pdfium_c

from paperus import page_layout

# Unix only; on Windows (the app's library on this computer) the helpers go
# without a memory limit.
if sys.platform != "win32":
    import resource

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
# A figure drawn for the screen: twice as sharp as the page, at most this
# wide or tall (pixels), with this much of the page around it (points).
FIGURE_SCALE = 2
FIGURE_MAX_SIDE = 1600
FIGURE_MARGIN = 2


class PdfError(Exception):
    """The PDF could not be read (damaged, too large, too slow)."""


_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()


def _limit_memory() -> None:
    # Where not allowed (some containers), the helper goes without.
    if sys.platform != "win32":
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


def annotations(path: Path) -> list[dict[str, Any]]:
    """The PDF's own annotations of the kinds paperus knows (see
    ``paperus.annotations``): each with ``kind``, ``page_index``,
    ``page_label``, ``rects`` or ``paths`` and ``width`` (PDF points),
    ``color`` ("#rrggbb"), ``text`` (marked, or written), ``comment``,
    ``font_size``."""
    return _run(_annotations, path)


def with_annotations(
    path: Path, out: Path, added: list[dict[str, Any]], removed: list[dict[str, Any]]
) -> None:
    """A copy of the PDF at ``out`` with ``added`` written in as standard
    PDF annotations (each as ``paperus.annotations`` keeps them: kind,
    page_index, position, color, text, comment) and the PDF's own
    annotations at ``removed`` ({page_index, rect}: taken in, so not
    twice) taken out."""
    _run(_with_annotations, path, str(out), added, removed)


def render(path: Path, index: int) -> bytes:
    """Page ``index`` (from 0) as a greyscale PNG, for OCR."""
    return _run(_render, path, index)


def figure(
    path: Path, index: int, box: page_layout.Figure, scale: float | None = None
) -> bytes:
    """A part of page ``index`` (from 0; ``box`` in points from its top
    left, as in its layout) as a colour PNG, for the screen; ``scale``:
    pixels per point (else ``FIGURE_SCALE``), at most ``FIGURE_MAX_SIDE``."""
    return _run(_figure, path, index, box, scale)


@dataclass
class Read:
    """A PDF read with its layouts."""

    pages: list[str]
    """The text of each page (empty where none)."""
    layouts: list[page_layout.PageLayout] | None
    """Each page's layout (``paperus.page_layout``); None if they could
    not be worked out."""
    pieces: list[list[page_layout.Part]] | None
    """Each page's text by its pieces, in reading order, captions apart
    (with ``layouts``)."""


def read(path: Path) -> Read:
    """The text of each page, and its layout with the text of its pieces,
    in one go."""
    return Read(*_run(_read, path))


def png(
    width: int, height: int, pixels: bytes, stride: int, channels: int = 1
) -> bytes:
    """An 8-bit greyscale (or, with three ``channels``, RGB) PNG of rows of
    pixels (``stride`` bytes apart)."""
    row = width * channels
    rows = b"".join(
        b"\0" + pixels[y * stride : y * stride + row] for y in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(
        ">IIBBBBB", width, height, 8, 2 if channels == 3 else 0, 0, 0, 0
    )
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


def _read(
    path: str,
) -> tuple[
    list[str], list[page_layout.PageLayout] | None, list[list[page_layout.Part]] | None
]:
    texts: list[str] = []
    layouts: list[page_layout.PageLayout] | None = []
    pieces: list[list[page_layout.Part]] = []
    with _open(path) as pdf:
        for index in range(len(pdf)):
            page = pdf[index]
            text_page = page.get_textpage()
            texts.append(text_page.get_text_bounded())
            text_page.close()
            if layouts is not None:
                try:
                    layout, own = page_layout.read(page, index == 0)
                    layouts.append(layout)
                    pieces.append(own)
                except Exception:
                    log.warning(
                        "no layout of page %d of %s", index + 1, path, exc_info=True
                    )
                    layouts = None
            page.close()
    return texts, layouts, pieces if layouts is not None else None


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


def _figure(
    path: str, index: int, box: page_layout.Figure, scale: float | None = None
) -> bytes:
    with _open(path) as pdf:
        page = pdf[index]
        try:
            width, height = page.get_size()
            if page.get_rotation() % 180:
                width, height = height, width
            m = FIGURE_MARGIN
            left = max(box["x"] - m, 0)
            top = max(box["y"] - m, 0)
            right = max(width - box["x"] - box["width"] - m, 0)
            bottom = max(height - box["y"] - box["height"] - m, 0)
            side = max(width - left - right, height - top - bottom, 1)
            bitmap = page.render(
                scale=min(scale or FIGURE_SCALE, FIGURE_MAX_SIDE / side),
                crop=(left, bottom, right, top),
                rev_byteorder=True,
                may_draw_forms=False,
            )
            try:
                return png(
                    bitmap.width,
                    bitmap.height,
                    bytes(bitmap.buffer),
                    bitmap.stride,
                    bitmap.n_channels,
                )
            finally:
                bitmap.close()
        finally:
            page.close()


# PDF annotation subtypes as paperus's kinds (squiggly as underline).
_KINDS = {
    pdfium_c.FPDF_ANNOT_HIGHLIGHT: "highlight",
    pdfium_c.FPDF_ANNOT_UNDERLINE: "underline",
    pdfium_c.FPDF_ANNOT_SQUIGGLY: "underline",
    pdfium_c.FPDF_ANNOT_STRIKEOUT: "strikeout",
    pdfium_c.FPDF_ANNOT_TEXT: "note",
    pdfium_c.FPDF_ANNOT_FREETEXT: "text",
    pdfium_c.FPDF_ANNOT_SQUARE: "image",
    pdfium_c.FPDF_ANNOT_INK: "ink",
}
_MARKS_TEXT = {"highlight", "underline", "strikeout"}
_FONT_SIZE = re.compile(rb"([\d.]+)\s+Tf")
_TEXT_COLOR = re.compile(rb"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg")
_TEXT_GREY = re.compile(rb"([\d.]+)\s+g\b")
_HIDDEN = 2
_LINE_WIDTH = re.compile(r"([\d.]+)\s+w\b")


def _wide(read: Callable[..., int], *args: object) -> str:
    """A UTF-16 string PDFium writes into a buffer (asked for its size first)."""
    size = read(*args, None, 0)
    if size <= 2:
        return ""
    buffer = (ctypes.c_ushort * (size // 2))()
    read(*args, buffer, size)
    return bytes(buffer)[: size - 2].decode("utf-16-le", errors="replace")


def _color(annot: Any) -> str | None:  # noqa: ANN401 (a PDFium handle)
    """Its colour (C). PDFium gives none while the annotation has a drawn
    appearance, so that is dropped first: only in this copy in memory,
    never saved."""
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    kind = pdfium_c.FPDFANNOT_COLORTYPE_Color
    if not pdfium_c.FPDFAnnot_GetColor(annot, kind, r, g, b, a):
        pdfium_c.FPDFAnnot_SetAP(annot, pdfium_c.FPDF_ANNOT_APPEARANCEMODE_NORMAL, None)
        if not pdfium_c.FPDFAnnot_GetColor(annot, kind, r, g, b, a):
            return None
    return f"#{r.value:02x}{g.value:02x}{b.value:02x}"


def _clean(text: str) -> str:
    """Words as read: hyphenation marks (U+0002, soft hyphens) joined up,
    control characters and spacing tidied."""
    text = re.sub(r"[\u0002\u00ad]\s*", "", text)
    text = re.sub(r"[\u0000-\u0008\u000b-\u001f]", " ", text)
    return " ".join(text.split())


def _rect(annot: Any) -> list[float] | None:  # noqa: ANN401
    """Where the annotation sits (its /Rect), lower left first."""
    rect = pdfium_c.FS_RECTF()
    if not pdfium_c.FPDFAnnot_GetRect(annot, rect):
        return None
    return [
        round(min(rect.left, rect.right), 3),
        round(min(rect.bottom, rect.top), 3),
        round(max(rect.left, rect.right), 3),
        round(max(rect.bottom, rect.top), 3),
    ]


def _rects(annot: Any) -> list[list[float]]:  # noqa: ANN401
    """Each marked line (its quad points), else the annotation's rect."""
    found = []
    for index in range(pdfium_c.FPDFAnnot_CountAttachmentPoints(annot)):
        quad = pdfium_c.FS_QUADPOINTSF()
        if pdfium_c.FPDFAnnot_GetAttachmentPoints(annot, index, quad):
            xs = [quad.x1, quad.x2, quad.x3, quad.x4]
            ys = [quad.y1, quad.y2, quad.y3, quad.y4]
            found.append([min(xs), min(ys), max(xs), max(ys)])
    if not found and (whole := _rect(annot)) is not None:
        found.append(whole)
    return [[round(v, 3) for v in r] for r in found]


def _paths(annot: Any) -> list[list[float]]:  # noqa: ANN401
    found = []
    for index in range(pdfium_c.FPDFAnnot_GetInkListCount(annot)):
        count = pdfium_c.FPDFAnnot_GetInkListPath(annot, index, None, 0)
        if count < 1:
            continue
        points = (pdfium_c.FS_POINTF * count)()
        pdfium_c.FPDFAnnot_GetInkListPath(annot, index, points, count)
        found.append([round(v, 2) for p in points for v in (p.x, p.y)])
    return found


def _line_width(annot: Any) -> float:  # noqa: ANN401
    """A pen stroke's width: as its drawn appearance has it ("2 w"), else
    its border (PDFium does not give /BS), else 1."""
    drawn = _wide(
        pdfium_c.FPDFAnnot_GetAP, annot, pdfium_c.FPDF_ANNOT_APPEARANCEMODE_NORMAL
    )
    if found := _LINE_WIDTH.search(drawn):
        return max(0.25, min(float(found.group(1)), 50.0))
    horizontal, vertical, width = (ctypes.c_float() for _ in range(3))
    if pdfium_c.FPDFAnnot_GetBorder(annot, horizontal, vertical, width):
        return max(0.25, min(width.value, 50.0)) if width.value > 0 else 1.0
    return 1.0


def _text_under(text_page: Any, rects: list[list[float]]) -> str:  # noqa: ANN401
    parts = []
    for left, bottom, right, top in rects:
        args = (text_page, left, top, right, bottom)
        count = pdfium_c.FPDFText_GetBoundedText(*args, None, 0)
        if count > 0:
            buffer = (ctypes.c_ushort * (count + 1))()
            pdfium_c.FPDFText_GetBoundedText(*args, buffer, count + 1)
            parts.append(bytes(buffer)[: count * 2].decode("utf-16-le", "replace"))
    return _clean(" ".join(parts))


def _annotations(path: str) -> list[dict[str, Any]]:
    found = []
    with _open(path) as pdf:
        for index in range(len(pdf)):
            page = pdf[index]
            text_page = page.get_textpage()
            label = _wide(pdfium_c.FPDF_GetPageLabel, pdf.raw, index) or None
            for number in range(pdfium_c.FPDFPage_GetAnnotCount(page.raw)):
                annot = pdfium_c.FPDFPage_GetAnnot(page.raw, number)
                try:
                    entry = _annotation(annot, text_page.raw)
                finally:
                    pdfium_c.FPDFPage_CloseAnnot(annot)
                if entry is not None:
                    found.append({**entry, "page_index": index, "page_label": label})
            text_page.close()
            page.close()
    return found


def _annotation(annot: Any, text_page: Any) -> dict[str, Any] | None:  # noqa: ANN401
    kind = _KINDS.get(pdfium_c.FPDFAnnot_GetSubtype(annot))
    if kind is None or pdfium_c.FPDFAnnot_GetFlags(annot) & _HIDDEN:
        return None
    where = _rect(annot)
    if where is None:
        return None
    # Before the colour: reading that may drop the drawn appearance.
    width = _line_width(annot) if kind == "ink" else None
    contents = _wide(pdfium_c.FPDFAnnot_GetStringValue, annot, b"Contents").strip()
    if kind == "text" and not contents:
        # Rich text (XHTML) only: its words.
        rich = _wide(pdfium_c.FPDFAnnot_GetStringValue, annot, b"RC")
        contents = re.sub(r"<[^>]+>", " ", rich).strip()
    entry: dict[str, Any] = {
        "kind": kind,
        "rect": where,
        "color": _color(annot),
        "comment": _clean(contents) if kind != "text" else contents,
        "text": None,
    }
    entry["comment"] = entry["comment"] or None
    if kind == "ink":
        entry["paths"] = _paths(annot)
        entry["width"] = width
        return entry if entry["paths"] else None
    entry["rects"] = _rects(annot)
    if not entry["rects"]:
        return None
    if kind in _MARKS_TEXT:
        entry["text"] = _text_under(text_page, entry["rects"]) or None
    elif kind == "text":
        # Words on the page: their contents are the words, not a comment.
        entry["text"], entry["comment"] = entry["comment"], None
        style = _wide(pdfium_c.FPDFAnnot_GetStringValue, annot, b"DA").encode()
        size = _FONT_SIZE.search(style)
        entry["font_size"] = float(size.group(1)) if size else 12.0
        # The words' colour is in the style (C is the box's background).
        if rgb := _TEXT_COLOR.search(style):
            channels = [min(255, round(float(v) * 255)) for v in rgb.groups()]
            entry["color"] = "#{:02x}{:02x}{:02x}".format(*channels)
        elif grey := _TEXT_GREY.search(style):
            level = min(255, round(float(grey.group(1)) * 255))
            entry["color"] = f"#{level:02x}{level:02x}{level:02x}"
        else:
            entry["color"] = "#000000"
    return entry


_SUBTYPES = {
    "highlight": pdfium_c.FPDF_ANNOT_HIGHLIGHT,
    "underline": pdfium_c.FPDF_ANNOT_UNDERLINE,
    "strikeout": pdfium_c.FPDF_ANNOT_STRIKEOUT,
    "note": pdfium_c.FPDF_ANNOT_TEXT,
    "text": pdfium_c.FPDF_ANNOT_FREETEXT,
    "image": pdfium_c.FPDF_ANNOT_SQUARE,
    "ink": pdfium_c.FPDF_ANNOT_INK,
}


def _set_text(annot: Any, key: bytes, value: str) -> None:  # noqa: ANN401
    encoded = value.encode("utf-16-le") + b"\0\0"
    buffer = (ctypes.c_ushort * (len(encoded) // 2)).from_buffer_copy(encoded)
    pdfium_c.FPDFAnnot_SetStringValue(annot, key, buffer)


def _write(page: Any, entry: dict[str, Any]) -> None:  # noqa: ANN401
    kind = entry["kind"]
    annot = pdfium_c.FPDFPage_CreateAnnot(page, _SUBTYPES[kind])
    if not annot:
        return
    try:
        color = entry.get("color") or "#ffd400"
        rgb = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
        position = entry.get("position") or {}
        rects = position.get("rects") or []
        if kind != "text":
            pdfium_c.FPDFAnnot_SetColor(
                annot, pdfium_c.FPDFANNOT_COLORTYPE_Color, *rgb, 255
            )
        for left, bottom, right, top in rects if kind in _MARKS_TEXT else []:
            quad = pdfium_c.FS_QUADPOINTSF(
                left, top, right, top, left, bottom, right, bottom
            )
            pdfium_c.FPDFAnnot_AppendAttachmentPoints(annot, quad)
        if kind == "ink":
            width = float(position.get("width") or 1)
            xs, ys = [], []
            for path in position.get("paths") or []:
                points = (pdfium_c.FS_POINTF * (len(path) // 2))()
                for i in range(len(path) // 2):
                    points[i].x, points[i].y = path[2 * i], path[2 * i + 1]
                    xs.append(path[2 * i])
                    ys.append(path[2 * i + 1])
                pdfium_c.FPDFAnnot_AddInkStroke(annot, points, len(path) // 2)
            pdfium_c.FPDFAnnot_SetBorder(annot, 0, 0, width)
            if xs:
                rects = [
                    [min(xs) - width, min(ys) - width, max(xs) + width, max(ys) + width]
                ]
        if rects:
            left = min(r[0] for r in rects)
            bottom = min(r[1] for r in rects)
            right = max(r[2] for r in rects)
            top = max(r[3] for r in rects)
            pdfium_c.FPDFAnnot_SetRect(
                annot, pdfium_c.FS_RECTF(left, top, right, bottom)
            )
        if kind == "text":
            size = float(position.get("font_size") or 12)
            r, g, b = (v / 255 for v in rgb)
            _set_text(annot, b"DA", f"/Helv {size:g} Tf {r:.3f} {g:.3f} {b:.3f} rg")
            _set_text(annot, b"Contents", entry.get("text") or "")
        elif entry.get("comment"):
            _set_text(annot, b"Contents", entry["comment"])
        pdfium_c.FPDFAnnot_SetFlags(annot, pdfium_c.FPDF_ANNOT_FLAG_PRINT)
    finally:
        pdfium_c.FPDFPage_CloseAnnot(annot)


def _with_annotations(
    path: str, out: str, added: list[dict[str, Any]], removed: list[dict[str, Any]]
) -> None:
    with _open(path) as pdf:
        for index in sorted({m["page_index"] for m in removed}):
            if index >= len(pdf):
                continue
            page = pdf[index]
            gone = [m["rect"] for m in removed if m["page_index"] == index]
            # From the end, so the numbers of those before stay.
            for number in reversed(range(pdfium_c.FPDFPage_GetAnnotCount(page.raw))):
                annot = pdfium_c.FPDFPage_GetAnnot(page.raw, number)
                where = _rect(annot)
                pdfium_c.FPDFPage_CloseAnnot(annot)
                if where and any(
                    all(abs(a - b) < 1 for a, b in zip(where, rect, strict=True))
                    for rect in gone
                ):
                    pdfium_c.FPDFPage_RemoveAnnot(page.raw, number)
            page.close()
        for entry in added:
            if entry["kind"] not in _SUBTYPES or entry["page_index"] >= len(pdf):
                continue
            page = pdf[entry["page_index"]]
            _write(page.raw, entry)
            page.close()
        pdf.save(out)
