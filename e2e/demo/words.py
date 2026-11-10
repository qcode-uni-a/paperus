"""The words the demo's recording searches for (record.ts): from the PDFs
given, read as paperus reads them (its passages), the ones worth finding:
four letters or more, in at least two passages, the most frequent first, at
most ``LIMIT``. Run with the server's environment:
``uv --directory server run python ../e2e/demo/words.py out.json a.pdf …``."""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from paperus.text import chunk_pages, extract_pdf_pages

LIMIT = 2500
MIN_PASSAGES = 2


def main(out: str, pdfs: list[str]) -> None:
    found: Counter[str] = Counter()
    for pdf in pdfs:
        for chunk in chunk_pages(extract_pdf_pages(Path(pdf))):
            found.update(set(re.findall(r"[^\W\d_]{4,}", chunk.text.lower())))
    words = [word for word, count in found.most_common() if count >= MIN_PASSAGES][
        :LIMIT
    ]
    Path(out).write_text(json.dumps(words, ensure_ascii=False))
    print(f"{len(words)} words to search for, of {len(found)}")


# PDFs are read in a helper process (paperus.pdf), which imports this again.
if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
