"""Importing from other reference managers: reading formats, adding them."""

import io
import json
import uuid
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.access import Access
from paperus.identifiers import Scheme
from paperus.importing import bibtex, csljson, ris
from paperus.importing.apply import NoFiles, Report, ZipFiles, apply
from paperus.models import User
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
