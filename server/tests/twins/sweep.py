"""Look for fluent mode's mistakes on the library's own PDFs: each page's
lines measured as for a twin (``measure.py``), the PDF's own text order
taken as the expected one, and the pages where fluent mode's pieces read
many lines out of that order, or leave lines out away from the page's
edges, drawn into ``OUT/index.html`` (worst first, as ``review.py`` draws
twins). Lines out of order within one piece do not count (a piece is shown
as it is). The PDF's order is often not the reading order (a caption, a
side panel first): look before believing. A page worth keeping becomes a
twin with ``measure.py``.

Run from ``server/``, with the library's database and files (the dev
servers' settings)::

    uv run python -m tests.twins.sweep OUT [--pages 3] [--worst 30]
"""

import bisect
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pypdfium2
from sqlalchemy import select

from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker
from paperus.models import File, Item, Version
from paperus.page_layout import analyse
from paperus.storage import blob_name
from tests.twins.check import check
from tests.twins.measure import measure
from tests.twins.review import SCALE, drawn

# Lines left out this far from the page's top and bottom (shares of its
# height) count; nearer, they are running headers and footers.
EDGE = 0.08


def longest_rising(values: list[int]) -> int:
    """The length of the longest run (not necessarily adjacent) that never
    falls."""
    tails: list[int] = []
    for value in values:
        i = bisect.bisect_right(tails, value)
        tails[i : i + 1] = [value]
    return len(tails)


def score(path: str, number: int) -> dict[str, Any] | None:
    """How far fluent mode's pieces read page ``number`` against the PDF's
    text order: lines in pieces out of order, and lines left out."""
    spec = measure(Path(path), number)
    body = [line for line in spec["lines"] if line["role"] == "body"]
    if len(body) < 10:
        return None
    with pypdfium2.PdfDocument(path) as document:
        layout = analyse(document[number - 1], number == 1)
    _, piece_of = check(spec, layout["columns"], layout["pieces"])
    height = spec["size"][1]
    read = [
        (line, piece_of[i])
        for i, line in enumerate(spec["lines"])
        if line["role"] == "body"
    ]
    pieces = [piece for line, piece in sorted(read, key=lambda r: r[0]["order"])]
    pieces = [piece for piece in pieces if piece >= 0]
    lost = [
        line["order"]
        for line, piece in read
        if piece < 0 and height * EDGE < line["box"][1] < height * (1 - EDGE)
    ]
    return {
        "misplaced": len(pieces) - longest_rising(pieces),
        "lost": len(lost),
        "pieces": len(layout["pieces"]),
        "columns": layout["columns"],
    }


def pages_of(job: tuple[str, str, str, int]) -> list[dict[str, Any]]:
    path, title, journal, pages = job
    try:
        with pypdfium2.PdfDocument(path) as document:
            count = len(document)
    except pypdfium2.PdfiumError:
        return []
    found = []
    for number in range(1, min(pages, count) + 1):
        try:
            result = score(path, number)
        except Exception as error:  # any page may break the measuring
            print(f"{path} p. {number}: {error!r}", file=sys.stderr)
            continue
        if result:
            found.append(
                {"path": path, "page": number, "title": title, "journal": journal}
                | result
            )
    return found


def main() -> None:
    out = Path(sys.argv[1])
    args = sys.argv[2:]
    pages = int(args[args.index("--pages") + 1]) if "--pages" in args else 3
    worst = int(args[args.index("--worst") + 1]) if "--worst" in args else 30
    out.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    with make_sessionmaker(make_engine(settings.database_url))() as db:
        rows = db.execute(
            select(File.blob_sha256, Item.title, Version.csl["container-title"].astext)
            .join(Version, File.version_id == Version.id)
            .join(Item, Item.id == Version.item_id)
            .where(
                File.media_type == "application/pdf",
                File.deleted_at.is_(None),
                Item.deleted_at.is_(None),
            )
        ).all()
    jobs: dict[bytes, tuple[str, str, str, int]] = {}
    for sha, title, journal in rows:
        path = settings.storage_path / "blobs" / blob_name(sha)
        if sha not in jobs and path.exists():
            jobs[sha] = (str(path), title, journal or "", pages)
    print(f"{len(jobs)} PDFs")
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor() as pool:
        for found in pool.map(pages_of, jobs.values(), chunksize=4):
            results.extend(found)
    (out / "results.json").write_text(json.dumps(results, indent=1))
    bad = sorted(
        (r for r in results if r["misplaced"] >= 5 or r["lost"] >= 3),
        key=lambda r: -(r["misplaced"] + r["lost"]),
    )
    cards = []
    for r in bad[:worst]:
        name = f"{Path(r['path']).name[:12]}-p{r['page']}"
        spec = measure(Path(r["path"]), r["page"])
        with pypdfium2.PdfDocument(r["path"]) as document:
            page = document[r["page"] - 1]
            layout = analyse(page, r["page"] == 1)
            _, piece_of = check(spec, layout["columns"], layout["pieces"])
            (out / f"{name}.png").write_bytes(
                drawn(page, spec, layout["pieces"], piece_of)
            )
        cards.append(
            f"<section><h2>{name}</h2><p>{r['journal']}: {r['title']}</p>"
            f"<p class=bad>{r['misplaced']} lines out of order, {r['lost']} left "
            f"out; {r['pieces']} pieces</p><img src='{name}.png' "
            f"width='{round(spec['size'][0] * SCALE / 2)}'></section>"
        )
    (out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Fluent mode sweep</title><style>"
        "body{font:14px system-ui;margin:24px;background:#f4f5f7}"
        "section{display:inline-block;vertical-align:top;margin:0 16px 24px 0;"
        "background:white;padding:12px;border-radius:8px;max-width:440px}"
        "h2{font-size:15px;margin:0}.bad{color:#b00020}"
        "img{border:1px solid #ddd}</style>" + "".join(cards)
    )
    print(
        f"{len(results)} pages, {len(bad)} flagged; the worst {len(cards)}: "
        f"{out / 'index.html'}"
    )


if __name__ == "__main__":
    main()
