"""Adding exports: papers met twice, trashed ones, large files, odd tags,
and the import job's own bookkeeping."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

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
from tests.people import Person, group
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


def test_papers_in_a_group_already(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    """Found in a group: counted by the group's name. Where the person may
    only read, a paper of their own instead, with the export's files (said
    so); without new files, the group's paper is all."""
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    lab, team = group(root, "Lab", bob), group(root, "Team", bob)
    bob.put(f"/api/groups/{lab['id']}/members/{ada.id}", json={"role": "reader"})
    bob.put(f"/api/groups/{team['id']}/members/{ada.id}", json={"role": "member"})
    for library, doi in ((lab, "10.1234/lab"), (team, "10.1234/team")):
        bob.post(
            "/api/items",
            json={
                "metadata": {"title": doi},
                "identifiers": [{"scheme": "doi", "value": doi}],
                "library_id": library["library_id"],
            },
        )
    ada.post(
        "/api/items",
        json={
            "metadata": {"title": "Mine"},
            "identifiers": [{"scheme": "doi", "value": "10.1234/mine"}],
        },
    )
    files = zipped(**{"a.pdf": PDF, "b.pdf": PDF + b"b", "c.pdf": PDF + b"c"})
    export = Export(
        format="csl-json",
        papers=[
            paper("In the lab", "a.pdf", doi="10.1234/lab"),
            paper("In the lab, without a file", doi="10.1234/lab"),
            paper("In the team", "b.pdf", doi="10.1234/team"),
            paper("Mine", doi="10.1234/mine"),
            paper("New", "c.pdf"),
        ],
    )
    report = apply(
        db, blobs, access_of(db, ada), export, files,
        owner=uuid.UUID(ada.libraries()["Me"]["id"]), max_file_bytes=1000,
    )  # fmt: skip
    assert (report.added, report.found) == (2, 2)
    assert report.found_elsewhere == {"Team": 1}
    assert report.own_copies == {"Lab": 1}

    # The team's paper got the file; the lab's did not, ada's copy did.
    def files_in(library: dict[str, Any]) -> list[int]:
        listed = bob.get("/api/items", params={"library": library["library_id"]})
        return [len(i["files"]) for i in listed.json()]

    assert (files_in(team), files_in(lab)) == ([1], [0])
    mine = ada.get("/api/items", params={"library": ada.libraries()["Me"]["id"]})
    assert sorted((i["title"], len(i["files"])) for i in mine.json()) == [
        ("In the lab", 1),
        ("Mine", 0),
        ("New", 1),
    ]


def test_an_ended_import_is_told(
    client: TestClient, db: Session, blobs: BlobStore, job_app: App
) -> None:
    ada = Person(client, db, "ada")
    response = client.post(
        "/api/imports",
        headers=ada.headers,
        files={"upload": ("library.bib", b"@article{a, title={A}}")},
    )
    assert response.status_code == 201
    [job] = imports(job_app)
    record = run_job(db, blobs, job)
    [notice] = ada.get("/api/me/notifications").json()["notifications"]
    assert notice["kind"] == "import"
    assert notice["data"] == {
        "import_id": str(record.id),
        "filename": "library.bib",
        "failed": False,
        "added": 1,
        "found": 0,
        "found_elsewhere": 0,
        "own_copies": 0,
        "problems": 0,
    }


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
