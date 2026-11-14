import struct
import uuid
from typing import Any

from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy import text
from sqlalchemy.orm import Session

from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.pdfs import make_pdf
from tests.people import Person
from tests.test_page_text import paper as two_columns

PAPER = make_pdf(
    [
        [
            "Drought indices in Bavaria",
            "We computed the SPEI at a 3-month scale.",
            "Daily station records from the weather service cover the years",
            "from 1961 to 2020, from the Alps in the south to the north.",
        ],
        [
            "Methods",
            "Gaps shorter than five days were filled",
            "by linear interpolation.",
        ],
    ]
)


def add_item(client: TestClient, title: str) -> str:
    response = client.post("/api/items", json={"metadata": {"title": title}})
    item_id: str = response.json()["id"]
    return item_id


def upload(
    client: TestClient,
    item_id: str,
    content: bytes = PAPER,
    filename: str = "paper.pdf",
    media_type: str = "application/pdf",
) -> dict[str, Any]:
    response = client.post(
        f"/api/items/{item_id}/files",
        files={"upload": (filename, content, media_type)},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def process(db: Session, blobs: BlobStore, file: dict[str, Any]) -> str:
    process_file(db, blobs, uuid.UUID(file["id"]))
    status = db.execute(
        text("SELECT text_status FROM files WHERE id = :id"),
        {"id": file["id"]},
    ).scalar_one()
    db.rollback()
    return str(status)


def search(client: TestClient, query: str) -> list[dict[str, Any]]:
    response = client.get("/api/search", params={"q": query})
    assert response.status_code == 200, response.text
    result: list[dict[str, Any]] = response.json()
    return result


def test_upload_queues_text_extraction(logged_in: TestClient, job_app: App) -> None:
    file = upload(logged_in, add_item(logged_in, "Paper"))
    assert file["text_status"] == "pending"
    assert isinstance(job_app.connector, InMemoryConnector)
    jobs = list(job_app.connector.jobs.values())
    assert [(j["task_name"], j["args"]) for j in jobs] == [
        ("paperus:extract_text", {"file_id": file["id"]})
    ]


def test_search_finds_passages_with_pages(
    logged_in: TestClient, db: Session, blobs: BlobStore
) -> None:
    item_id = add_item(logged_in, "Drought paper")
    file = upload(logged_in, item_id)
    assert search(logged_in, "SPEI") == []
    assert process(db, blobs, file) == "done"

    [hit] = search(logged_in, "SPEI")
    assert hit["item_id"] == item_id
    assert hit["item_title"] == "Drought paper"
    assert (hit["item_authors"], hit["item_year"]) == ([], None)
    assert hit["file_id"] == file["id"]
    assert hit["page"] == 1
    assert hit["passage_id"] == f"{file['id']}#0"
    assert "<mark>SPEI</mark>" in hit["snippet"]
    # The passage's text, to find it on the page.
    text = logged_in.get(f"/api/files/{file['id']}/passages/0").json()
    assert text["page"] == 1
    assert "SPEI" in text["text"] and "<mark>" not in text["text"]
    assert logged_in.get(f"/api/files/{file['id']}/passages/99").status_code == 404

    [hit] = search(logged_in, '"linear interpolation"')
    assert hit["page"] == 2
    assert search(logged_in, "interpolation -linear") == []


def test_snippets_are_html_safe(
    logged_in: TestClient, db: Session, blobs: BlobStore
) -> None:
    content = b"Results <script>alert(1)</script> & discussion of runoff"
    file = upload(
        logged_in, add_item(logged_in, "Notes"), content, "notes.md", "text/markdown"
    )
    assert process(db, blobs, file) == "done"
    [hit] = search(logged_in, "runoff")
    assert "<script>" not in hit["snippet"]
    assert "&lt;script&gt;" in hit["snippet"]
    assert "&amp;" in hit["snippet"]
    assert hit["page"] is None


def test_trashed_items_and_files_are_not_found(
    logged_in: TestClient, db: Session, blobs: BlobStore
) -> None:
    item_id = add_item(logged_in, "Paper")
    file = upload(logged_in, item_id)
    process(db, blobs, file)
    logged_in.delete(f"/api/files/{file['id']}")
    assert search(logged_in, "SPEI") == []
    logged_in.post(f"/api/files/{file['id']}/restore")
    assert len(search(logged_in, "SPEI")) == 1
    logged_in.delete(f"/api/items/{item_id}")
    assert search(logged_in, "SPEI") == []


def test_same_contents_reuse_chunks(
    logged_in: TestClient, db: Session, blobs: BlobStore
) -> None:
    first = upload(logged_in, add_item(logged_in, "A"))
    second = upload(logged_in, add_item(logged_in, "B"))
    process(db, blobs, first)
    # The second file's blob could even be gone: its chunks are copied.
    assert process(db, blobs, second) == "done"
    hits = search(logged_in, "SPEI")
    assert {h["item_title"] for h in hits} == {"A", "B"}


def test_files_without_text(
    logged_in: TestClient, db: Session, blobs: BlobStore
) -> None:
    item_id = add_item(logged_in, "Odd files")
    scanned = upload(logged_in, item_id, make_pdf([[], []]), "scan.pdf")
    assert process(db, blobs, scanned) == "no_text"
    binary = upload(
        logged_in, item_id, b"\x00\x01", "data.bin", "application/octet-stream"
    )
    assert process(db, blobs, binary) == "unsupported"
    broken = upload(logged_in, item_id, b"%PDF-1.4 but nothing else", "broken.pdf")
    assert process(db, blobs, broken) == "failed"


def test_search_needs_login_and_a_query(
    client: TestClient, logged_in: TestClient
) -> None:
    assert logged_in.get("/api/search").status_code == 422
    logged_in.post("/api/auth/logout")
    assert client.get("/api/search", params={"q": "x"}).status_code == 401


def test_best_few_per_paper_and_within_one(
    logged_in: TestClient, db: Session, blobs: BlobStore
) -> None:
    """One paper full of hits does not fill the list; a search within one
    paper gets the rest of its hits."""
    long = make_pdf(
        [
            [
                f"{n}. Drought",
                "Drought again in this year.",
                "Rivers ran low from spring on, and the wells of the region fell",
                "to their lowest level since records began in the old town.",
            ]
            for n in range(1, 9)
        ]
    )
    many, few = add_item(logged_in, "Many droughts"), add_item(logged_in, "Few")
    process(db, blobs, upload(logged_in, many, long, "long.pdf"))
    process(db, blobs, upload(logged_in, few))
    found = logged_in.get(
        "/api/search", params={"q": "drought", "mode": "keyword", "per_item": 2}
    ).json()
    titles = [p["item_title"] for p in found]
    assert titles.count("Many droughts") == 2 and "Few" in titles
    within = logged_in.get(
        "/api/search", params={"q": "drought", "mode": "keyword", "item": many}
    ).json()
    assert len(within) > 2 and {p["item_id"] for p in within} == {many}


def test_results_name_authors_and_year(
    logged_in: TestClient, db: Session, blobs: BlobStore
) -> None:
    """How people recognise a paper: "Vicente-Serrano et al. (2010)"."""
    metadata = {
        "title": "A multiscalar drought index",
        "author": [
            {"family": "Vicente-Serrano", "given": "Sergio"},
            {"family": "Beguería", "given": "Santiago"},
        ],
        "issued": {"date-parts": [[2010, 4]]},
    }
    item_id = logged_in.post("/api/items", json={"metadata": metadata}).json()["id"]
    assert process(db, blobs, upload(logged_in, item_id)) == "done"
    [hit] = search(logged_in, "SPEI")
    assert hit["item_authors"] == ["Vicente-Serrano, Sergio", "Beguería, Santiago"]
    assert hit["item_year"] == 2010


def test_figures_found_by_their_captions(
    logged_in: TestClient, db: Session, blobs: BlobStore
) -> None:
    """A figure's caption is a passage of its own, marked: found as that
    figure, and alone with ``figures=true``."""
    item_id = add_item(logged_in, "Columns")
    assert process(db, blobs, upload(logged_in, item_id, two_columns())) == "done"
    found = logged_in.get(
        "/api/search", params={"q": "figure of tests", "mode": "keyword"}
    ).json()
    [figure] = [p for p in found if p["caption"]]
    assert (figure["figure"], figure["page"]) == ("FIG. 1", 1)
    only = logged_in.get(
        "/api/search", params={"q": "tests", "mode": "keyword", "figures": True}
    ).json()
    assert [p["passage_id"] for p in only] == [figure["passage_id"]]

    # Its figure found on the page, drawn for the result (without its
    # caption); the browser's copy is still it.
    assert figure["figure_image"] is True
    assert 200 <= figure["figure_width"] <= 220 <= 2 * figure["figure_height"]
    assert 295 <= figure["figure_top"] <= 300 and 322 <= figure["figure_left"] <= 326
    url = f"/api/files/{figure['file_id']}/figure"
    drawn = logged_in.get(url, params={"page": 1, "label": "FIG. 1"})
    assert drawn.status_code == 200, drawn.text
    assert drawn.headers["content-type"] == "image/png"
    assert drawn.content.startswith(b"\x89PNG")
    width, height = struct.unpack(">II", drawn.content[16:24])
    assert 400 <= width <= 450 and 230 <= height <= 260  # 216 x 119 points, twice
    again = logged_in.get(
        url,
        params={"page": 1, "label": "FIG. 1"},
        headers={"If-None-Match": drawn.headers["etag"]},
    )
    assert again.status_code == 304
    for params in ({"page": 1, "label": "FIG. 2"}, {"page": 9, "label": "FIG. 1"}):
        assert logged_in.get(url, params=params).status_code == 404
    other = Person(logged_in, db, "other")
    assert other.get(f"{url}?page=1&label=FIG.%201").status_code == 404
