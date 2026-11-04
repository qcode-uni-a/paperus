"""Small PDFs with real text, for tests."""


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[str]], title: str | None = None) -> bytes:
    """A PDF with one page per entry, each entry a list of text lines."""
    objects: list[bytes] = []
    page_count = len(pages)
    font_id = 3
    first_page_id = 4
    kids = " ".join(f"{first_page_id + 2 * i} 0 R" for i in range(page_count))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, lines in enumerate(pages):
        content_id = first_page_id + 2 * i + 1
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
                f" /Resources << /Font << /F1 {font_id} 0 R >> >>"
                f" /Contents {content_id} 0 R >>"
            ).encode()
        )
        text = "".join(f"({_escape(line)}) Tj T* " for line in lines)
        stream = f"BT /F1 11 Tf 14 TL 72 720 Td {text}ET".encode()
        objects.append(
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
        )

    info = ""
    if title is not None:
        objects.append(f"<< /Title ({_escape(title)}) >>".encode())
        info = f" /Info {len(objects)} 0 R"

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R%s >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        info.encode(),
        xref,
    )
    return bytes(out)
