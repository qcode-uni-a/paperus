"""Adding exports: papers met twice, trashed ones, large files, odd tags,
and the import job's own bookkeeping."""

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy.orm import Session

from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedFile, ExportedPaper
from paperus.importing.apply import Report, apply
from paperus.importing.run import run_import
from paperus.models import Import, User
from paperus.storage import BlobStore
from tests.people import Person
from tests.test_import import access_of, zip_bytes, zipped

PDF = b"%PDF-1.4\n% a small file\n"


def paper(title: str, *files: str, doi: str | None = None) -> ExportedPaper:
    return ExportedPaper(
        csl={"type": "article-journal", "title": title},
        identifiers=[(Scheme.DOI, doi)] if doi else [],
        files=[ExportedFile(path=f) for f in files],
        source_key=title,
    )


def test_papers_met_again(client: TestClient, db: Session, blobs: BlobStore) -> None:
    ada = Person(client, db, "ada")
    owner = uuid.UUID(ada.libraries()["Me"]["id"])
    # In the trash: importing it again brings it back, as adding it would.
    gone = ada.post(
        "/api/items",
        json={
            "metadata": {"title": "Gone"},
            "identifiers": [{"scheme": "doi", "value": "10.1234/gone"}],
        },
    ).json()
    assert ada.delete(f"/api/items/{gone['id']}").status_code == 204
    files = zipped(**{"files/1/one.pdf": PDF, "big.bin": b"x" * 5000})

    def run(*papers: ExportedPaper) -> Report:
        export = Export(format="csl-json", papers=list(papers))
        return apply(
            db, blobs, access_of(db, ada), export, files, owner=owner,
            max_file_bytes=1000,
        )  # fmt: skip

    odd_tags = paper("One", "files/1/one.pdf", doi="10.1234/one")
    odd_tags.tags = [" ", "ok"]
    report = run(
        odd_tags,
        paper("One, as a second entry", doi="10.1234/one"),
        paper("Big", "big.bin"),
        paper("Gone again", doi="10.1234/gone"),
    )
    assert (report.added, report.found, report.files) == (2, 2, 1)
    assert report.problems == ["big.bin: too large"]
    titles = {i["title"]: i for i in ada.get("/api/items").json()}
    assert set(titles) == {"One", "Big", "Gone"}
    one = ada.get(f"/api/items/{titles['One']['id']}").json()
    assert [t["name"] for t in one["tags"]] == ["ok"]

    # Another entry with a file the library has already: that paper.
    again = run(paper("One under another name", "files/1/one.pdf"))
    assert (again.added, again.found, again.files) == (0, 1, 0)


def run_job(db: Session, blobs: BlobStore, job: dict[str, object]) -> Import:
    args = job["args"]
    assert isinstance(args, dict)
    record = db.get(Import, uuid.UUID(args["import_id"]))
    assert record is not None and record.blob_sha256 is not None
    with blobs.local_file(record.blob_sha256) as path:
        run_import(db, blobs, record, path=path, max_file_bytes=10_000_000)
    db.refresh(record)
    return record


def imports(job_app: App) -> list[dict[str, object]]:
    assert isinstance(job_app.connector, InMemoryConnector)
    return [
        job
        for job in job_app.connector.jobs.values()
        if job["task_name"] == "paperus:import_library"
    ]


def test_an_upload_waiting_twice_is_kept_for_the_second(
    client: TestClient, db: Session, blobs: BlobStore, job_app: App
) -> None:
    ada = Person(client, db, "ada")
    upload = zip_bytes(**{"library.bib": b"@article{a, title={A}}"})
    for _ in range(2):
        response = client.post(
            "/api/imports",
            headers=ada.headers,
            files={"upload": ("library.zip", upload)},
        )
        assert response.status_code == 201
    first, second = imports(job_app)
    sha = hashlib.sha256(upload).digest()
    assert run_job(db, blobs, first).status == "done"
    assert blobs.exists(sha)  # the second import still needs it
    assert run_job(db, blobs, second).status == "done"
    assert not blobs.exists(sha)


def test_an_import_of_someone_who_left(
    client: TestClient, db: Session, blobs: BlobStore, job_app: App
) -> None:
    ada = Person(client, db, "ada")
    response = client.post(
        "/api/imports",
        headers=ada.headers,
        files={"upload": ("library.bib", b"@article{a, title={A}}")},
    )
    assert response.status_code == 201
    user = db.get(User, uuid.UUID(ada.id))
    assert user is not None
    user.deactivated_at = datetime.now(UTC)
    db.commit()
    [job] = imports(job_app)
    record = run_job(db, blobs, job)
    assert (record.status, record.error) == (
        "failed",
        "The person who started the import cannot log in.",
    )
    assert record.blob_sha256 is None
