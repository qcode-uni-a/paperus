"""Importing from other reference managers: reading formats, adding them."""

import hashlib
import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy.orm import Session

from paperus.access import Access
from paperus.cli import main
from paperus.identifiers import Scheme
from paperus.importing import (
    Export,
    ExportedFile,
    ExportedPaper,
    bibtex,
    csljson,
    ris,
    zotero,
)
from paperus.importing import apply as apply_module
from paperus.importing.apply import NoFiles, Report, ZipFiles, apply
from paperus.importing.run import run_import
from paperus.models import Import, User
from paperus.storage import BlobStore
from tests.pdfs import make_pdf
from tests.people import Person, group

BIB = r"""% Encoding: UTF-8

@Article{vanGogh2024,
  author    = {van Gogh, Vincent and M{\"u}ller, Jr., J{\"o}rg
               and {Radar Working Group}},
  title     = {Radar gaps \& {AI} over the {Alps}: $\alpha$-fields},
  journal   = {Journal of Weather},
  year      = {2024},
  month     = mar,
  volume    = {12},
  number    = {4},
  pages     = {101--120},
  doi       = {https://doi.org/10.1234/RADAR},
  keywords  = {radar, weather; alps},
  groups    = {Chapter 1},
  file      = {:C\:/Users/Ada/Papers/vangogh.pdf:PDF;
               Supplement:files/12/missing.pdf:application/pdf},
  annote    = {Read for chapter 1. Good figures.},
}

@Misc{lovelace2026,
  author        = {Ada Lovelace},
  title         = {The diffusion of rain},
  year          = {2026},
  eprint        = {2611.00001v2},
  archivePrefix = {arXiv},
}

@Article{vanGogh2024,
  title = {Duplicate key},
}

@Comment{jabref-meta: grouping:
0 AllEntriesGroup:;
1 StaticGroup:Thesis\;0\;1\;0x8a8a8aff\;\;\;;
2 StaticGroup:Chapter 1\;0\;1\;0x8a8a8aff\;\;\;;
}
"""

RIS = """TY  - JOUR
AU  - van Gogh, Vincent
TI  - Radar gaps over the Alps
JO  - Journal of Weather
PY  - 2024
DA  - 2024/03/02/
SP  - 101
EP  - 120
DO  - 10.1234/radar
KW  - radar
N1  - From Mendeley.
L1  - file:///C:/Users/Ada/Mendeley/vangogh.pdf
ER  -

TY  - GEN
AU  - Lovelace, Ada
TI  - The diffusion of rain
PY  - 2026
UR  - http://arxiv.org/abs/2611.00001v2
ER  -
"""


def test_bibtex() -> None:
    export = bibtex.read(BIB)
    assert export.collections == [("Thesis",), ("Thesis", "Chapter 1")]
    assert export.problems == [
        "The key vanGogh2024 appears more than once; also imported as vanGogh2024-2."
    ]
    article, preprint, _ = export.papers
    assert article.csl == {
        "type": "article-journal",
        "title": "Radar gaps & AI over the Alps: $\\alpha$-fields",
        "author": [
            {"family": "Gogh", "given": "Vincent", "non-dropping-particle": "van"},
            {"family": "Müller", "given": "Jörg", "suffix": "Jr."},
            {"literal": "Radar Working Group"},
        ],
        "container-title": "Journal of Weather",
        "issued": {"date-parts": [[2024, 3]]},
        "volume": "12",
        "issue": "4",
        "page": "101-120",
        "DOI": "10.1234/radar",
        "citation-key": "vanGogh2024",
    }
    assert article.identifiers == [(Scheme.DOI, "10.1234/radar")]
    assert article.tags == ["radar", "weather", "alps"]
    assert article.collections == [("Thesis", "Chapter 1")]
    assert article.notes == ["Read for chapter 1. Good figures."]
    assert [f.path for f in article.files] == [
        "C:/Users/Ada/Papers/vangogh.pdf",
        "files/12/missing.pdf",
    ]
    assert preprint.csl["type"] == "article"
    assert preprint.identifiers == [(Scheme.ARXIV, "2611.00001")]


def test_bibtex_that_is_not() -> None:
    assert bibtex.read("@article{x, title={unclosed").problems


def test_ris() -> None:
    export = ris.read(RIS)
    article, preprint = export.papers
    assert article.csl["issued"] == {"date-parts": [[2024, 3, 2]]}
    assert article.csl["page"] == "101-120"
    assert article.csl["author"] == [{"family": "van Gogh", "given": "Vincent"}]
    assert (article.tags, article.notes) == (["radar"], ["From Mendeley."])
    assert article.files[0].path == "/C:/Users/Ada/Mendeley/vangogh.pdf"
    assert preprint.identifiers == [(Scheme.ARXIV, "2611.00001")]
    assert preprint.csl["type"] == "article"


def test_csl_json() -> None:
    export = csljson.read(
        json.dumps(
            [
                {
                    "id": "http://zotero.org/users/1/items/ABC",
                    "type": "book",
                    "title": "Clouds",
                    "ISBN": "978-3-16-148410-0",
                    "citation-key": "clouds2020",
                },
                {"id": "x"},
            ]
        )
    )
    [book] = export.papers
    assert book.csl == {
        "type": "book",
        "title": "Clouds",
        "ISBN": "978-3-16-148410-0",
        "citation-key": "clouds2020",
    }
    assert book.identifiers == [(Scheme.ISBN, "9783161484100")]
    assert export.problems == ["Entry 2 has no title and was skipped."]


def access_of(db: Session, person: Person) -> Access:
    user = db.get(User, uuid.UUID(person.id))
    assert user is not None
    return Access.of(db, user)


def zipped(**files: bytes) -> ZipFiles:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return ZipFiles(zipfile.ZipFile(buffer))


def test_apply(client: TestClient, db: Session, blobs: BlobStore) -> None:
    ada = Person(client, db, "ada")
    pdf = make_pdf([["Radar gaps over the Alps"]])
    # Ada has the arXiv paper already, with a tag of her own.
    known = ada.post(
        "/api/items",
        json={
            "metadata": {"title": "Diffusion of rain (preprint)"},
            "identifiers": [{"scheme": "arxiv", "value": "2611.00001"}],
        },
    ).json()
    added_files: list[uuid.UUID] = []
    owner = uuid.UUID(ada.libraries()["Me"]["id"])

    def run() -> Report:
        return apply(
            db,
            blobs,
            access_of(db, ada),
            bibtex.read(BIB),
            zipped(**{"library.bib": BIB.encode(), "Papers/vangogh.pdf": pdf}),
            owner=owner,
            max_file_bytes=10_000_000,
            file_added=added_files.append,
        )

    report = run()
    assert report.papers == 3
    assert (report.added, report.found) == (2, 1)
    assert (report.files, report.notes, report.collections) == (1, 1, 2)
    assert report.missing_files == ["files/12/missing.pdf"]
    assert len(added_files) == 1

    items = {i["title"]: i for i in ada.get("/api/items").json()}
    assert set(items) == {
        "Radar gaps & AI over the Alps: $\\alpha$-fields",
        "Diffusion of rain (preprint)",
        "Duplicate key",
    }
    article = ada.get(
        f"/api/items/{items['Radar gaps & AI over the Alps: $\\alpha$-fields']['id']}"
    ).json()
    assert [t["name"] for t in article["tags"]] == ["alps", "radar", "weather"]
    [version] = article["versions"]
    assert version["metadata_source"] == "import"
    assert [f["filename"] for f in version["files"]] == ["vangogh.pdf"]
    assert version["files"][0]["role"] == "main"
    collections = {c["name"]: c for c in ada.get("/api/collections").json()}
    assert collections["Chapter 1"]["parent_id"] == collections["Thesis"]["id"]
    assert article["collection_ids"] == [collections["Chapter 1"]["id"]]
    [note] = ada.get(f"/api/notes?item={article['id']}").json()
    assert note["title"] == "Read for chapter 1. Good figures."
    # The known preprint was found, not added again.
    assert known["id"] in {i["id"] for i in items.values()}

    # Importing again adds nothing.
    again = run()
    assert (again.added, again.found) == (0, 3)
    assert (again.files, again.notes, again.collections) == (0, 0, 0)
    assert len(ada.get("/api/items").json()) == 3


def test_apply_to_a_group_and_without_files(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    report = apply(
        db,
        blobs,
        access_of(db, ada),
        ris.read(RIS),
        NoFiles(),
        owner=uuid.UUID(chair["library_id"]),
        max_file_bytes=10_000_000,
    )
    assert (report.added, report.missing_files) == (
        2,
        ["/C:/Users/Ada/Mendeley/vangogh.pdf"],
    )
    # The group's members see them; readers may not import into the group.
    assert len(bob.get("/api/items").json()) == 2
    try:
        apply(
            db,
            blobs,
            access_of(db, bob),
            ris.read(RIS),
            NoFiles(),
            owner=uuid.UUID(chair["library_id"]),
            max_file_bytes=10_000_000,
        )
    except Exception as error:
        assert "readers" in str(error)
    else:
        raise AssertionError("a reader imported into the group")


def zip_bytes(**files: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def run_queued(db: Session, blobs: BlobStore, job_app: App) -> list[str]:
    """Run the queued imports as the worker would; the files they queued."""
    assert isinstance(job_app.connector, InMemoryConnector)
    queued: list[str] = []
    for job in list(job_app.connector.jobs.values()):
        if job["task_name"] != "paperus:import_library":
            continue
        record = db.get(Import, uuid.UUID(job["args"]["import_id"]))
        assert record is not None and record.blob_sha256 is not None
        with blobs.local_file(record.blob_sha256) as path:
            run_import(
                db,
                blobs,
                record,
                path=path,
                max_file_bytes=10_000_000,
                file_added=lambda file_id: queued.append(str(file_id)),
            )
    return queued


def test_upload_and_progress(
    client: TestClient, db: Session, blobs: BlobStore, job_app: App
) -> None:
    ada = Person(client, db, "ada")
    pdf = make_pdf([["Radar gaps over the Alps"]])
    upload = zip_bytes(
        **{
            "My Library/My Library.bib": BIB.encode(),
            "My Library/files/vangogh.pdf": pdf,
        }
    )
    response = client.post(
        "/api/imports",
        headers=ada.headers,
        files={"upload": ("My Library.zip", upload, "application/zip")},
    )
    assert response.status_code == 201, response.text
    started = response.json()
    assert (started["status"], started["filename"]) == ("waiting", "My Library.zip")

    queued = run_queued(db, blobs, job_app)
    assert len(queued) == 1  # the PDF, for its text
    done = ada.get(f"/api/imports/{started['id']}").json()
    assert (done["status"], done["format"]) == ("done", "bibtex")
    assert done["done"] == done["total"] == 3
    report = done["report"]
    assert (report["added"], report["files"], report["collections"]) == (3, 1, 2)
    assert report["missing_files"] == ["files/12/missing.pdf"]
    assert [i["id"] for i in ada.get("/api/imports").json()] == [started["id"]]
    # Someone else's import is not visible.
    bob = Person(client, db, "bob")
    assert bob.get(f"/api/imports/{started['id']}").status_code == 404


def test_upload_formats_and_failures(
    client: TestClient, db: Session, blobs: BlobStore, job_app: App
) -> None:
    ada = Person(client, db, "ada")

    def upload(name: str, data: bytes) -> dict[str, Any]:
        response = client.post(
            "/api/imports", headers=ada.headers, files={"upload": (name, data)}
        )
        assert response.status_code == 201, response.text
        result: dict[str, Any] = response.json()
        return result

    imports = {
        "ris": upload("export.ris", RIS.encode()),
        "rdf": upload("Exported Items.rdf", b'<?xml version="1.0"?>\n<rdf:RDF/>'),
        "nothing": upload("notes.txt", b"just words"),
        "zip": upload("empty.zip", zip_bytes(**{"a.pdf": b"%PDF-1.4"})),
    }
    run_queued(db, blobs, job_app)
    result = {k: ada.get(f"/api/imports/{v['id']}").json() for k, v in imports.items()}
    assert (result["ris"]["status"], result["ris"]["format"]) == ("done", "ris")
    assert (result["rdf"]["status"], result["rdf"]["format"]) == ("done", "zotero-rdf")
    assert "not an export paperus can read" in result["nothing"]["error"]
    assert "No .rdf, .bib, .ris or .json file in the zip" in result["zip"]["error"]


def test_import_command(
    client: TestClient,
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ada = Person(client, db, "ada")
    folder = tmp_path / "export"
    (folder / "Papers").mkdir(parents=True)
    (folder / "library.bib").write_text(BIB)
    (folder / "Papers" / "vangogh.pdf").write_bytes(make_pdf([["Radar"]]))
    monkeypatch.setenv("PAPERUS_DATABASE_URL", database_url)
    monkeypatch.setenv("PAPERUS_STORAGE_PATH", str(tmp_path / "files"))
    with pytest.raises(SystemExit) as exit:
        main(["import", str(folder), "--user", "ada"])
    assert exit.value.code == 0
    out = capsys.readouterr().out
    assert "3 papers: 3 added, 0 already there; 1 files" in out
    assert "Missing file: files/12/missing.pdf" in out
    assert len(ada.get("/api/items").json()) == 3
    with pytest.raises(SystemExit) as exit:
        main(["import", str(folder), "--user", "ada", "--group", "Nowhere"])
    assert exit.value.code == 1


ZOTERO = (Path(__file__).parent / "zotero_sample.rdf").read_text()


def test_zotero_rdf() -> None:
    export = zotero.read(ZOTERO)
    assert export.problems == []
    assert export.collections == [("Thesis",), ("Thesis", "Chapter 1")]
    [standalone] = export.notes
    assert (standalone.text, standalone.collections) == (
        "Ideas for the thesis.",
        [("Thesis",)],
    )
    papers = {p.csl["title"]: p for p in export.papers}
    article = papers["Radar gaps over the Alps"]
    assert article.csl["author"] == [
        {"family": "van Gogh", "given": "Vincent"},
        {"literal": "Radar Working Group"},
    ]
    assert article.csl["translator"] == [{"family": "Müller", "given": "Jörg"}]
    assert article.csl["container-title"] == "Journal of Weather"
    assert (article.csl["volume"], article.csl["issue"]) == ("12", "4")
    assert article.csl["citation-key"] == "vanGogh2024"
    assert article.csl["note"] == "Read twice."
    assert article.csl["accessed"] == {"date-parts": [[2026, 1, 5]]}
    assert article.identifiers == [(Scheme.DOI, "10.1234/radar")]
    assert article.tags == ["Weather", "radar"]  # automatic tags too
    assert article.collections == [("Thesis", "Chapter 1")]
    assert article.notes == [
        "# Reading notes\n\nThe **gaps** are below the beam.\n\n- one\n- two"
    ]
    # Only the stored file; the link to a web page has none.
    assert [f.path for f in article.files] == [
        "files/13/van Gogh - 2024 - Radar gaps.pdf"
    ]
    preprint = papers["The diffusion of rain"]
    assert preprint.csl["type"] == "article"
    assert preprint.identifiers == [(Scheme.ARXIV, "2611.00001")]
    book = papers["Clouds"]
    assert (book.csl["publisher"], book.csl["publisher-place"]) == (
        "Cloud Press",
        "Augsburg",
    )
    assert book.csl["collection-title"] == "Weather Studies"
    assert book.identifiers == [(Scheme.ISBN, "9783161484100")]
    # A file on its own in Zotero becomes a document of its own.
    note = papers["Note241029"]
    assert note.csl["type"] == "document"
    assert [f.path for f in note.files] == ["files/30/Note241029.pdf"]
    assert (note.tags, note.collections) == (["handwritten"], [("Thesis",)])
    # Downloaded from arXiv: Zotero kept the address, so the ID is known.
    arxiv_file = papers["2601"]
    assert arxiv_file.identifiers == [(Scheme.ARXIV, "2601.01704")]
    assert arxiv_file.csl["type"] == "article"
    assert arxiv_file.csl["URL"] == "https://arxiv.org/pdf/2601.01704v1"
    assert len(export.papers) == 5
    assert zotero.read("<rdf:RDF").problems


def test_zotero_zip(
    client: TestClient, db: Session, blobs: BlobStore, job_app: App
) -> None:
    ada = Person(client, db, "ada")
    upload = zip_bytes(
        **{
            "Exported Items/Exported Items.rdf": ZOTERO.encode(),
            "Exported Items/files/13/van Gogh - 2024 - Radar gaps.pdf": make_pdf(
                [["Radar"]]
            ),
            "Exported Items/files/30/Note241029.pdf": make_pdf([["Scribbles"]]),
            "Exported Items/files/31/2601.pdf": make_pdf([["Floquet"]]),
        }
    )
    started = client.post(
        "/api/imports",
        headers=ada.headers,
        files={"upload": ("Exported Items.zip", upload)},
    ).json()
    run_queued(db, blobs, job_app)
    done = ada.get(f"/api/imports/{started['id']}").json()
    assert (done["status"], done["format"]) == ("done", "zotero-rdf")
    report = done["report"]
    assert (report["added"], report["files"], report["notes"]) == (5, 3, 2)
    assert report["missing_files"] == []
    thesis = next(
        c for c in ada.get("/api/collections").json() if c["name"] == "Thesis"
    )
    [note] = ada.get(f"/api/notes?collection={thesis['id']}&nested=false").json()
    assert note["title"] == "Ideas for the thesis."


def test_one_failing_paper_does_not_break_the_rest(
    client: TestClient, db: Session, blobs: BlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    ada = Person(client, db, "ada")
    text = """
@article{a, title={First}, groups={Reading}}
@article{b, title={Second}, groups={Reading}}
@article{c, title={Third}, groups={Reading}}
"""
    real = apply_module._paper

    def flaky(run: Any, paper: Any) -> None:  # noqa: ANN401
        real(run, paper)
        if paper.source_key == "a":
            raise ValueError("broken entry\nwith SQL below")

    monkeypatch.setattr(apply_module, "_paper", flaky)
    report = apply(
        db,
        blobs,
        access_of(db, ada),
        bibtex.read(text),
        NoFiles(),
        owner=uuid.UUID(ada.libraries()["Me"]["id"]),
        max_file_bytes=10_000_000,
    )
    # The first was undone, also in the counts; the others went in, into the
    # collection the first had made (and that was undone with it).
    assert (report.added, report.collections) == (2, 1)
    assert report.problems == ["a: broken entry"]
    assert sorted(i["title"] for i in ada.get("/api/items").json()) == [
        "Second",
        "Third",
    ]


def test_hostile_and_odd_exports() -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">&b;</rdf:RDF>'
    )
    assert "entities" in zotero.read(bomb).problems[0]
    odd = csljson.read(
        json.dumps(
            [
                {"type": "article", "title": "A", "PMID": 12345, "DOI": ["10.1234/a"]},
                {"type": "article", "title": "B", "author": "not a list"},
            ]
        )
    )
    assert odd.papers[0].identifiers == [
        (Scheme.DOI, "10.1234/a"),
        (Scheme.PMID, "12345"),
    ]


def test_reimport_skips_standalone_notes_and_drops_the_upload(
    client: TestClient, db: Session, blobs: BlobStore, job_app: App
) -> None:
    ada = Person(client, db, "ada")
    upload = zip_bytes(**{"Exported Items.rdf": ZOTERO.encode()})
    for _ in range(2):
        response = client.post(
            "/api/imports",
            headers=ada.headers,
            files={"upload": ("Exported Items.zip", upload)},
        )
        assert response.status_code == 201
        run_queued(db, blobs, job_app)
        assert isinstance(job_app.connector, InMemoryConnector)
        job_app.connector.jobs.clear()
    reports = [i["report"] for i in ada.get("/api/imports").json()]
    assert [r["notes"] for r in reports] == [0, 2]  # newest first
    # The uploaded zip is gone once imported.
    sha = hashlib.sha256(upload).digest()
    assert not blobs.exists(sha)


def test_same_file_names_in_a_zip_folder() -> None:
    """arXiv snapshots are often all called 2310.html: in a zip with a top
    folder, each is still found by its whole path."""
    files = zipped(
        **{
            "My Library/files/83/2310.html": b"first",
            "My Library/files/373/2310.html": b"second",
        }
    )
    for path, content in (
        ("files/83/2310.html", b"first"),
        ("files/373/2310.html", b"second"),
    ):
        opened = files.open(path)
        assert opened is not None
        assert opened.read() == content
    # From the exporting computer, also with a different start.
    absolute = files.open("C:/Users/ada/Zotero/files/373/2310.html")
    assert absolute is not None and absolute.read() == b"second"
    assert files.open("files/999/2310.html") is None


def test_importing_again_repeats_nothing(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    """Papers without identifiers or files (e.g. web pages saved in Zotero)
    are recognised by type and title when the same export comes again; two
    such entries of one title in an export stay two."""
    ada = Person(client, db, "ada")
    owner = uuid.UUID(ada.libraries()["Me"]["id"])
    page = {"type": "webpage", "title": "Gauge principle in two-level systems"}
    export = Export(
        format="zotero-rdf",
        papers=[ExportedPaper(csl=dict(page)), ExportedPaper(csl=dict(page))],
    )

    def run() -> Report:
        return apply(
            db, blobs, access_of(db, ada), export, NoFiles(), owner=owner,
            max_file_bytes=10**6,
        )  # fmt: skip

    first = run()
    assert (first.added, first.found) == (2, 0)
    again = run()
    assert (again.added, again.found) == (0, 2)
    assert len(ada.get("/api/items").json()) == 2


def test_snapshots_next_to_a_pdf_are_left_out() -> None:
    pdf = ExportedFile(path="files/1/paper.pdf", media_type="application/pdf")
    page = ExportedFile(path="files/2/2310.html", media_type="text/html")
    slides = ExportedFile(path="files/3/talk.pptx", media_type=None)
    assert zotero._without_snapshots([page, pdf, slides]) == [pdf, slides]
    # Alone, the snapshot is the paper's only text: it stays.
    assert zotero._without_snapshots([page]) == [page]
