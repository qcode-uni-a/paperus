# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx==0.28.1"]
# ///
"""A small library for the update test (see run.sh), through the API.

    uv run library.py fill  URL STATE   on the last release: people, a group,
                                         papers, a PDF, tags, a collection,
                                         notes and an annotation; what was
                                         made goes into STATE (JSON)
    uv run library.py check URL STATE   on the new version: all still there,
                                         and each person sees what they did

``fill`` talks to the last release, so when the API it uses changes, this
script follows only once that change is released.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

ADA = {"username": "ada", "password": "update-test-ada"}
BEN = {"username": "ben", "password": "update-test-ben"}
WORD = "fluorescence"
"""In the PDF's text only, so keyword search finds it there."""
ABSTRACT_WORD = "birefringence"
"""In the typed-in paper's abstract only."""


def pdf(lines: list[str]) -> bytes:
    """A one-page PDF with these lines of text (as server/tests/pdfs.py)."""
    text = "".join(
        "({}) Tj T* ".format(
            line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        )
        for line in lines
    )
    stream = f"BT /F1 11 Tf 14 TL 72 720 Td {text}ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            " /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>"
        ),
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return out


def ok(response: httpx.Response) -> httpx.Response:
    if response.is_error:
        sys.exit(
            f"{response.request.method} {response.request.url}: "
            f"{response.status_code} {response.text}"
        )
    return response


def client(url: str, token: str | None = None) -> httpx.Client:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.Client(base_url=url, headers=headers, timeout=30)


def log_in(url: str, person: dict[str, str]) -> httpx.Client:
    with client(url) as anonymous:
        token = ok(anonymous.post("/api/auth/login", json=person)).json()["token"]
    return client(url, token)


def read(api: httpx.Client, item_id: str) -> None:
    """Wait until the item's files are read (text, details from the file)."""
    for _ in range(120):
        if not ok(api.get(f"/api/items/{item_id}")).json()["processing"]:
            return
        time.sleep(1)
    sys.exit(f"item {item_id} is still being read after two minutes")


def fill(url: str) -> dict[str, str]:
    with client(url) as anonymous:
        token = ok(anonymous.post("/api/setup/admin", json=ADA)).json()["token"]
    ada = client(url, token)
    ben_id = ok(ada.post("/api/admin/users", json=BEN)).json()["id"]
    group = ok(ada.post("/api/groups", json={"name": "Optics lab"})).json()
    ok(ada.put(f"/api/groups/{group['id']}/members/{ben_id}", json={"role": "member"}))

    # A PDF in the group's library, read by the worker.
    content = pdf(
        [
            "Measuring lifetimes in thin films",
            "A. Lovelace",
            f"We report {WORD} lifetimes of dyes in thin polymer films.",
        ]
    )
    upload = ok(
        ada.post(
            "/api/uploads",
            files={"upload": ("lifetimes.pdf", content, "application/pdf")},
            data={"library_id": group["library_id"]},
        )
    ).json()
    shared = upload["item_id"]
    read(ada, shared)

    # A paper typed in, in Ada's own library.
    own = ok(
        ada.post(
            "/api/items",
            json={
                "metadata": {
                    "type": "article-journal",
                    "title": "Crystals and polarised light",
                    "author": [{"family": "Lovelace", "given": "Ada"}],
                    "issued": {"date-parts": [[1843]]},
                    "abstract": f"On {ABSTRACT_WORD} in calcite.",
                }
            },
        )
    ).json()["id"]

    ok(ada.post(f"/api/items/{shared}/tags", json={"name": "spectroscopy"}))
    collection = ok(
        ada.post(
            "/api/collections",
            json={"name": "Thin films", "library_id": group["library_id"]},
        )
    ).json()["id"]
    ok(ada.post(f"/api/collections/{collection}/items", json={"item_ids": [shared]}))
    me = ok(ada.get("/api/auth/me")).json()
    libraries = ok(ada.get("/api/libraries")).json()
    own_library = next(
        lib["id"] for lib in libraries if lib["id"] != group["library_id"]
    )
    private_note = ok(
        ada.post(
            "/api/notes",
            json={
                "text": "# Ada's reading notes\n\nCheck the dye concentration.",
                "library_id": own_library,
                "items": [{"item_id": shared, "page": 1}],
            },
        )
    ).json()["id"]
    group_note = ok(
        ada.post(
            "/api/notes",
            json={
                "text": "# Lab meeting\n\nBen orders new films.",
                "library_id": group["library_id"],
                "collection_id": collection,
            },
        )
    ).json()["id"]

    details = ok(ada.get(f"/api/items/{shared}")).json()
    file = details["versions"][0]["files"][0]
    annotation = ok(
        ada.post(
            f"/api/files/{file['id']}/annotations",
            json={
                "kind": "highlight",
                "page_index": 0,
                "position": {"rects": [[72, 690, 400, 702]]},
                "text": f"{WORD} lifetimes",
                "comment": "Compare with the 2019 values.",
            },
        )
    ).json()["id"]
    return {
        "ada_id": me["id"],
        "ben_id": ben_id,
        "group_id": group["id"],
        "group_library_id": group["library_id"],
        "shared": shared,
        "shared_title": details["title"],
        "own": own,
        "collection": collection,
        "private_note": private_note,
        "group_note": group_note,
        "file": file["id"],
        "sha256": hashlib.sha256(content).hexdigest(),
        "annotation": annotation,
    }


def expect(condition: bool, what: str) -> None:
    print(("ok    " if condition else "FAIL  ") + what)
    if not condition:
        expect.failed = True  # type: ignore[attr-defined]


def check(url: str, made: dict[str, str]) -> None:
    ada, ben = log_in(url, ADA), log_in(url, BEN)
    expect(True, "Ada and Ben log in with their passwords")

    shared = ok(ada.get(f"/api/items/{made['shared']}")).json()
    expect(shared["title"] == made["shared_title"], "the PDF's paper keeps its title")
    expect([t["name"] for t in shared["tags"]] == ["spectroscopy"], "its tag is there")
    expect(shared["collection_ids"] == [made["collection"]], "it is in the collection")
    content = ok(ada.get(f"/api/files/{made['file']}/content")).content
    expect(
        hashlib.sha256(content).hexdigest() == made["sha256"],
        "its PDF comes back unchanged",
    )
    own = ok(ada.get(f"/api/items/{made['own']}")).json()
    expect(
        (own["title"], own["year"]) == ("Crystals and polarised light", 1843),
        "the typed-in paper keeps its details",
    )

    notes = {
        note: ok(ada.get(f"/api/notes/{made[note]}")).json()
        for note in ("private_note", "group_note")
    }
    expect(
        notes["private_note"]["text"].endswith("Check the dye concentration.")
        and [link["item_id"] for link in notes["private_note"]["items"]]
        == [made["shared"]],
        "Ada's private note keeps its text and its paper",
    )
    expect(
        notes["group_note"]["collection_ids"] == [made["collection"]],
        "the group's note is in the collection",
    )
    annotations = ok(ada.get(f"/api/files/{made['file']}/annotations")).json()
    expect(
        [a["comment"] for a in annotations["annotations"]]
        == ["Compare with the 2019 values."],
        "Ada's highlight keeps its comment",
    )

    members = ok(ada.get(f"/api/groups/{made['group_id']}/members")).json()
    expect(
        {m["username"]: m["role"] for m in members}.get("ben") == "member",
        "Ben is still a member of the group",
    )
    expect(
        ben.get(f"/api/items/{made['shared']}").status_code == 200
        and ben.get(f"/api/notes/{made['group_note']}").status_code == 200,
        "Ben sees the group's paper and note",
    )
    expect(
        ben.get(f"/api/items/{made['own']}").status_code == 404
        and ben.get(f"/api/notes/{made['private_note']}").status_code == 404,
        "Ben does not see Ada's own paper or her private note",
    )

    found = ok(ada.get("/api/search", params={"q": WORD, "mode": "keyword"})).json()
    expect(
        made["shared"] in {p["item_id"] for p in found},
        "keyword search finds the PDF by a word in its text",
    )
    found = ok(
        ada.get("/api/search", params={"q": ABSTRACT_WORD, "mode": "keyword"})
    ).json()
    expect(
        made["own"] in {p["item_id"] for p in found},
        "keyword search finds the typed-in paper by its abstract",
    )
    if getattr(expect, "failed", False):
        sys.exit(1)


def main() -> None:
    command, url, state = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    if command == "fill":
        state.write_text(json.dumps(fill(url), indent=2))
    elif command == "check":
        check(url, json.loads(state.read_text()))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
