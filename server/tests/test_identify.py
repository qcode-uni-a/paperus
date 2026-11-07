import hashlib
import uuid
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.identifiers import Scheme
from paperus.identify import (
    find_identifiers,
    identifiers_in_filename,
    identify,
    plausible_title,
    title_appears,
)
from paperus.models import File
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.conftest import FakeDOIRegistry
from tests.pdfs import make_pdf

DOI = "10.1234/drought.2024.5"
CSL = {
    "type": "journal-article",
    "title": "Drought indices for Bavarian rivers",
    "author": [{"family": "Huber", "given": "Anna"}],
    "container-title": "Journal of Hydrology",
    "issued": {"date-parts": [[2024]]},
}
FIRST_PAGE = [
    "Journal of Hydrology 612 (2024) 128-140",
    "Drought indices for Bavarian rivers",
    "Anna Huber",
    f"https://doi.org/{DOI}.",
]


def test_find_identifiers() -> None:
    text = (
        "See doi:10.1000/ABC.1), and https://doi.org/10.2000/x-y; "
        "arXiv:2101.00001v2 [cs.LG] again 10.1000/abc.1"
    )
    assert find_identifiers(text) == [
        (Scheme.DOI, "10.1000/abc.1"),
        (Scheme.DOI, "10.2000/x-y"),
        (Scheme.ARXIV, "2101.00001"),
    ]


def test_title_appears() -> None:
    page = "Journal X\nDrought indices for Bavarian rivers\nAnna Huber"
    assert title_appears("Drought Indices for Bavarian Rivers", page)
    assert not title_appears("A completely different paper about soils", page)


@pytest.mark.parametrize(
    ("title", "ok"),
    [
        ("Drought indices for Bavarian rivers", True),
        ("Microsoft Word - draft3.docx", False),
        ("paper.pdf", False),
        ("Untitled", False),
        ("short", False),
        ("my_upload_file", False),
        (None, False),
    ],
)
def test_plausible_title(title: str | None, ok: bool) -> None:
    assert plausible_title(title, "my_upload_file.pdf") == ok


def upload(
    client: TestClient, content: bytes, name: str = "scan_0042.pdf"
) -> dict[str, Any]:
    response = client.post(
        "/api/uploads", files={"upload": (name, content, "application/pdf")}
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def run_job(
    db: Session, blobs: BlobStore, registry: FakeDOIRegistry, file_id: str
) -> None:
    http = httpx2.Client(transport=httpx2.MockTransport(registry))
    process_file(db, blobs, uuid.UUID(file_id), http)


def get_item(client: TestClient, item_id: str) -> dict[str, Any]:
    result: dict[str, Any] = client.get(f"/api/items/{item_id}").json()
    return result


def test_upload_creates_placeholder_item(logged_in: TestClient) -> None:
    uploaded = upload(logged_in, make_pdf([FIRST_PAGE]))
    item = get_item(logged_in, uploaded["item_id"])
    assert item["title"] == "scan_0042"
    assert item["processing"] is True
    assert item["versions"][0]["metadata_source"] == "file"
    assert item["versions"][0]["files"] == [uploaded["file"]]


def test_doi_in_pdf_replaces_placeholder(
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    doi_registry: FakeDOIRegistry,
) -> None:
    doi_registry.records[DOI] = CSL
    uploaded = upload(logged_in, make_pdf([FIRST_PAGE, ["Introduction ..."]]))
    run_job(db, blobs, doi_registry, uploaded["file"]["id"])

    item = get_item(logged_in, uploaded["item_id"])
    assert item["title"] == "Drought indices for Bavarian rivers"
    assert item["authors"] == ["Huber, Anna"]
    assert item["container_title"] == "Journal of Hydrology"
    assert item["identifiers"] == [{"scheme": "doi", "value": DOI}]
    assert item["processing"] is False
    [version] = item["versions"]
    assert version["metadata_source"] == "lookup"
    assert version["kind"] == "published"


def test_arxiv_id_in_pdf(
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    doi_registry: FakeDOIRegistry,
) -> None:
    doi_registry.records["10.48550/arxiv.2101.00001"] = {
        **CSL,
        "type": "article-journal",
    }
    page = ["arXiv:2101.00001v2 [physics.ao-ph] 5 Jan 2021", *FIRST_PAGE[1:3]]
    uploaded = upload(logged_in, make_pdf([page]))
    run_job(db, blobs, doi_registry, uploaded["file"]["id"])

    item = get_item(logged_in, uploaded["item_id"])
    assert item["title"] == "Drought indices for Bavarian rivers"
    assert item["type"] == "article"
    assert item["versions"][0]["kind"] == "preprint"
    assert {"scheme": "arxiv", "value": "2101.00001"} in item["identifiers"]


def test_cited_doi_with_other_title_is_ignored(
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    doi_registry: FakeDOIRegistry,
) -> None:
    doi_registry.records[DOI] = {**CSL, "title": "Soil moisture in the Alps"}
    uploaded = upload(logged_in, make_pdf([FIRST_PAGE]))
    run_job(db, blobs, doi_registry, uploaded["file"]["id"])
    item = get_item(logged_in, uploaded["item_id"])
    assert item["title"] == "scan_0042"
    assert item["versions"][0]["metadata_source"] == "file"


def test_known_paper_joins_the_existing_item(
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    doi_registry: FakeDOIRegistry,
) -> None:
    doi_registry.records[DOI] = CSL
    existing = logged_in.post("/api/items", json={"doi": DOI}).json()
    uploaded = upload(logged_in, make_pdf([FIRST_PAGE]))
    # Dropped on a collection's page, with a tag, before it was recognized.
    shelf = logged_in.post("/api/collections", json={"name": "Shelf"}).json()["id"]
    logged_in.post(
        f"/api/collections/{shelf}/items", json={"item_ids": [uploaded["item_id"]]}
    )
    logged_in.post(f"/api/items/{uploaded['item_id']}/tags", json={"name": "drought"})
    run_job(db, blobs, doi_registry, uploaded["file"]["id"])
    db.expire_all()

    assert logged_in.get(f"/api/items/{uploaded['item_id']}").status_code == 404
    item = get_item(logged_in, existing["id"])
    [version] = item["versions"]
    [file] = version["files"]
    assert file["id"] == uploaded["file"]["id"]
    assert file["role"] == "main"
    assert item["collection_ids"] == [shelf]
    assert [t["name"] for t in item["tags"]] == ["drought"]

    # Another copy (other bytes) of the same paper is kept as a further file.
    again = upload(logged_in, make_pdf([FIRST_PAGE, ["Accepted manuscript"]]))
    run_job(db, blobs, doi_registry, again["file"]["id"])
    db.expire_all()
    files = get_item(logged_in, existing["id"])["versions"][0]["files"]
    assert [f["role"] for f in files] == ["main", "other"]


def test_same_file_again_makes_no_new_item(logged_in: TestClient) -> None:
    content = make_pdf([FIRST_PAGE])
    first = upload(logged_in, content)
    response = logged_in.post(
        "/api/uploads", files={"upload": ("copy.pdf", content, "application/pdf")}
    )
    assert response.status_code == 200
    again = response.json()
    assert again["existing"] is True
    assert again["item_id"] == first["item_id"]
    assert again["file"] == first["file"]
    assert len(logged_in.get("/api/items").json()) == 1

    sha256 = hashlib.sha256(content).hexdigest()
    known = logged_in.get(f"/api/uploads/{sha256}").json()
    assert known["item_id"] == first["item_id"]
    assert logged_in.get(f"/api/uploads/{'0' * 64}").status_code == 404
    assert logged_in.get("/api/uploads/xyz").status_code == 422

    # A copy in the trash does not count.
    logged_in.delete(f"/api/items/{first['item_id']}")
    assert logged_in.get(f"/api/uploads/{sha256}").status_code == 404
    assert upload(logged_in, content)["item_id"] != first["item_id"]


def test_embedded_title_without_identifier(
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    doi_registry: FakeDOIRegistry,
) -> None:
    pdf = make_pdf([["Some notes without identifiers"]], title="Notes on river gauges")
    uploaded = upload(logged_in, pdf)
    run_job(db, blobs, doi_registry, uploaded["file"]["id"])
    item = get_item(logged_in, uploaded["item_id"])
    assert item["title"] == "Notes on river gauges"
    assert item["versions"][0]["metadata_source"] == "file"


def test_manual_metadata_is_never_replaced(
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    doi_registry: FakeDOIRegistry,
) -> None:
    doi_registry.records[DOI] = CSL
    item = logged_in.post(
        "/api/items", json={"metadata": {"title": "My own title"}}
    ).json()
    file = logged_in.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("p.pdf", make_pdf([FIRST_PAGE]), "application/pdf")},
    ).json()
    run_job(db, blobs, doi_registry, file["id"])
    assert get_item(logged_in, item["id"])["title"] == "My own title"


def test_failing_lookup_keeps_the_text(
    logged_in: TestClient, db: Session, blobs: BlobStore
) -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("offline")

    uploaded = upload(logged_in, make_pdf([FIRST_PAGE]))
    http = httpx2.Client(transport=httpx2.MockTransport(broken))
    process_file(db, blobs, uuid.UUID(uploaded["file"]["id"]), http)
    item = get_item(logged_in, uploaded["item_id"])
    assert item["processing"] is False
    assert item["title"] == "scan_0042"
    hits = logged_in.get("/api/search", params={"q": "Bavarian"}).json()
    assert len(hits) == 1


@pytest.mark.parametrize(
    ("name", "found"),
    [
        ("2611.04892v1.pdf", [(Scheme.ARXIV, "2611.04892")]),
        ("arXiv_2101.00001.pdf", [(Scheme.ARXIV, "2101.00001")]),
        ("paper 2101.00001.pdf", []),
        ("scan_0042.pdf", []),
    ],
)
def test_identifiers_in_filename(name: str, found: list[tuple[Scheme, str]]) -> None:
    assert identifiers_in_filename(name) == found


def test_arxiv_id_from_filename(
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    doi_registry: FakeDOIRegistry,
) -> None:
    doi_registry.records["10.48550/arxiv.2101.00001"] = CSL
    pdf = make_pdf([FIRST_PAGE[1:3]])
    uploaded = upload(logged_in, pdf, name="2101.00001v3.pdf")
    run_job(db, blobs, doi_registry, uploaded["file"]["id"])
    item = get_item(logged_in, uploaded["item_id"])
    assert item["title"] == "Drought indices for Bavarian rivers"
    assert {"scheme": "arxiv", "value": "2101.00001"} in item["identifiers"]


def test_odd_identifiers_in_text() -> None:
    # Cut off at punctuation, or a letter only case-insensitive matching
    # takes for "s": no identifier.
    assert find_identifiers("doi 10.1234/) and arXiv:\u017folv-int/9901001") == []
    assert not title_appears("A b", "A b")


def test_only_uploaded_pdfs_with_text_are_identified(
    db: Session, blobs: BlobStore, doi_registry: FakeDOIRegistry
) -> None:
    http = httpx2.Client(transport=httpx2.MockTransport(doi_registry))
    identify(db, blobs, http, uuid.uuid4())  # gone: nothing to do
    assert doi_registry.requests == []


def test_a_file_without_uploader(
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    doi_registry: FakeDOIRegistry,
) -> None:
    """Files fetched by paperus itself (no uploader) are looked up in their
    own library only."""
    doi_registry.records[DOI] = CSL
    uploaded = upload(logged_in, make_pdf([FIRST_PAGE]))
    file = db.get(File, uuid.UUID(uploaded["file"]["id"]))
    assert file is not None
    file.uploaded_by = None
    db.commit()
    run_job(db, blobs, doi_registry, uploaded["file"]["id"])
    assert get_item(logged_in, uploaded["item_id"])["title"] == CSL["title"]


def test_a_known_paper_in_the_trash_is_not_joined(
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    doi_registry: FakeDOIRegistry,
) -> None:
    doi_registry.records[DOI] = CSL
    existing = logged_in.post("/api/items", json={"doi": DOI}).json()
    logged_in.delete(f"/api/items/{existing['id']}")
    uploaded = upload(logged_in, make_pdf([FIRST_PAGE]))
    run_job(db, blobs, doi_registry, uploaded["file"]["id"])
    db.expire_all()
    # The upload stays as it was; the trash is not where it goes.
    item = get_item(logged_in, uploaded["item_id"])
    assert (item["title"], item["deleted_at"]) == ("scan_0042", None)


def test_a_known_paper_with_the_same_file(
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    doi_registry: FakeDOIRegistry,
) -> None:
    doi_registry.records[DOI] = CSL
    content = make_pdf([FIRST_PAGE])
    uploaded = upload(logged_in, content)
    existing = logged_in.post("/api/items", json={"doi": DOI}).json()
    added = logged_in.post(
        f"/api/items/{existing['id']}/files",
        files={"upload": ("drought.pdf", content, "application/pdf")},
    )
    assert added.status_code == 201, added.text
    run_job(db, blobs, doi_registry, uploaded["file"]["id"])
    db.expire_all()
    assert logged_in.get(f"/api/items/{uploaded['item_id']}").status_code == 404
    [file] = get_item(logged_in, existing["id"])["versions"][0]["files"]
    assert file["id"] == added.json()["id"]
