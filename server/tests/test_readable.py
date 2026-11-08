"""The readable copy of the library (storage template)."""

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus import readable
from paperus.storage import BlobStore, FilesystemStore
from tests.pdfs import make_pdf
from tests.people import Person, group

PDF = b"%PDF-1.7\n" + b"x" * 3000 + b"\n%%EOF\n"
SLIDES = b"%PDF-1.7\n" + b"s" * 3000 + b"\n%%EOF\n"


def add(person: Person, metadata: dict[str, Any], library: str | None = None) -> str:
    response = person.post(
        "/api/items", json={"metadata": metadata, "library_id": library}
    )
    assert response.status_code == 201, response.text
    item: str = response.json()["id"]
    return item


def upload(person: Person, item: str, data: bytes, name: str = "p.pdf") -> None:
    response = person.post(
        f"/api/items/{item}/files", files={"upload": (name, data, "application/pdf")}
    )
    assert response.status_code == 201, response.text


def test_template_check() -> None:
    assert readable.check_template("{year}/{title}") == "{year}/{title}"
    for bad, says in [
        ("{nope}", "unknown variable"),
        ("{title:>10}", "no format"),
        ("{title", "stray brace"),
        ("plain", "at least one variable"),
    ]:
        with pytest.raises(readable.TemplateError, match=says):
            readable.check_template(bad)


def test_render_cleans_names() -> None:
    values = readable.values_for(
        {
            "title": 'Rain: why? "Clouds" / drops',
            "author": [{"family": "Lovelace"}, {"family": "Babbage"}],
            "issued": {"date-parts": [[1843]]},
            "DOI": "10.1/x",
        },
        "Chair",
        "notes.pdf",
        "main",
    )
    assert values["authors"] == "Lovelace and Babbage"
    path = readable.render(
        "{owner}/../{year} {first_author} - {title} {doi}", values, ".pdf"
    )
    assert path == "Chair/1843 Lovelace - Rain why Clouds drops 10.1_x.pdf"
    assert readable.render("/{title}/", {"title": ".."}, "") == "_"


def test_sync_writes_renames_and_removes(
    client: TestClient, db: Session, blobs: BlobStore, tmp_path: Path
) -> None:
    root_admin = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    chair = group(root_admin, "Chair", ada)
    paper = add(
        ada,
        {
            "title": "Notes on the engine",
            "container-title": "Nature Physics",
            "container-title-short": "Nat. Phys.",
            "author": [{"family": "Lovelace"}],
            "issued": {"date-parts": [[1843]]},
        },
        library=chair["library_id"],
    )
    upload(ada, paper, PDF)
    upload(ada, paper, SLIDES, "talk.pdf")
    mine = add(ada, {"title": "Draft"})
    upload(ada, mine, PDF)

    root = tmp_path / "copy"
    root.mkdir()
    (root / "mine.txt").write_text("not paperus's")
    template = readable.DEFAULT_TEMPLATE
    report = readable.sync(db, blobs, root, template, links=False)
    assert report.error is None
    assert (report.files, report.written, report.removed) == (3, 3, 0)
    main = root / "Chair" / "Lovelace_NatPhys_1843.pdf"
    assert main.read_bytes() == PDF
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.pdf"))
    assert files[0] == "Chair/Lovelace_NatPhys_1843 (2).pdf"
    assert files[1:] == [
        "Chair/Lovelace_NatPhys_1843.pdf",
        "ada/Unknown_document_n.d.pdf",
    ]
    assert (root / files[0]).read_bytes() == SLIDES
    again = readable.sync(db, blobs, root, template, links=False)
    assert (again.written, again.removed) == (0, 0)

    # A new template: the old names go, the new ones come; others' files stay.
    report = readable.sync(db, blobs, root, "{owner}/{title}", links=False)
    assert (report.written, report.removed) == (3, 3)
    assert not (root / "Chair" / "Lovelace_NatPhys_1843.pdf").exists()
    assert (root / "Chair" / "Notes on the engine.pdf").exists()
    assert (root / "mine.txt").read_text() == "not paperus's"
    assert readable.last_report(db) == report

    readable.remove_copy(db, root)
    assert sorted(p.name for p in root.rglob("*")) == ["mine.txt"]


def test_hard_links(
    client: TestClient, db: Session, blobs: BlobStore, tmp_path: Path
) -> None:
    assert isinstance(blobs, FilesystemStore)
    ada = Person(client, db, "ada")
    paper = add(ada, {"title": "Linked"})
    upload(ada, paper, PDF)
    root = blobs.root.parent / "copy"
    readable.sync(db, blobs, root, "{title}", links=True)
    copy = root / "Linked.pdf"
    stored = next((blobs.root / "blobs").glob("*/*/*"))
    assert os.stat(copy).st_ino == os.stat(stored).st_ino


def test_settings_and_preview(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    # Being an administrator reads no library: not in the preview.
    ada = Person(client, db, "ada")
    upload(ada, add(ada, {"title": "Ada's own"}), make_pdf([["Private"]]))
    paper = add(root, {"title": "Shown", "issued": {"date-parts": [[2020]]}})
    upload(root, paper, PDF)
    preview = root.post(
        "/api/admin/readable-copy/preview", json={"template": "{year}/{title}"}
    ).json()
    assert preview == {"paths": ["2020/Shown.pdf"], "error": None}
    bad = root.post("/api/admin/readable-copy/preview", json={"template": "{x}"})
    assert bad.json()["error"] == "unknown variable {x}"

    config = root.get("/api/admin/config").json()
    assert config["copy_template"] == readable.DEFAULT_TEMPLATE
    refused = root.put("/api/admin/config", json={**config, "copy_template": "{x}"})
    assert refused.status_code == 422
    info = root.get("/api/admin/readable-copy").json()
    assert info["report"] is None
    assert info["links_possible"] is True
    assert "title" in info["variables"]


def test_long_titles_end_at_a_word() -> None:
    title = (
        "The nonlinear physics and statistical field theory"
        " of twilight clouds hovering dynamics"
    )
    values = readable.values_for({"title": title}, "me", "x.pdf", "main")
    assert values["title"] == (
        "The nonlinear physics and statistical field theory of twilight clouds hovering"
    )


def test_journal_names() -> None:
    def journal(**csl: Any) -> str:  # noqa: ANN401
        return readable.values_for(csl, "me", "x.pdf", "main")["journal"]

    assert journal(**{"container-title-short": "Phys. Rev. Lett."}) == "PhysRevLett"
    assert (
        journal(**{"container-title": "nature communications"})
        == "NatureCommunications"
    )
    assert journal(publisher="MIT Press", type="book") == "MITPress"
    assert journal(type="article") == "preprint"
    assert journal(type="thesis") == "thesis"


def test_long_journal_name() -> None:
    csl = {"container-title": "Physical Review Letters", "container-title-short": "PRL"}
    values = readable.values_for(csl, "me", "x.pdf", "main")
    assert (values["journal"], values["journal_long"]) == (
        "PRL",
        "Physical Review Letters",
    )
    assert (
        readable.values_for({"type": "thesis"}, "me", "x", "main")["journal_long"]
        == "thesis"
    )


def test_journal_names_in_lists() -> None:
    csl = {"container-title": ["Nature", "Nat."], "container-title-short": []}
    values = readable.values_for(csl, "me", "x.pdf", "main")
    assert (values["journal"], values["journal_long"]) == ("Nature", "Nature")
    long = {"container-title": [], "container-title-short": ["Nat."]}
    assert readable.values_for(long, "me", "x.pdf", "main")["journal_long"] == "Nat."


def test_roles_trash_and_copies_instead_of_links(
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ada = Person(client, db, "ada")
    paper = add(ada, {"title": "Engines"})
    upload(ada, paper, PDF)
    version = ada.get(f"/api/items/{paper}").json()["versions"][0]["id"]
    slides = client.post(
        f"/api/versions/{version}/files",
        headers=ada.headers,
        files={"upload": ("talk.pdf", SLIDES, "application/pdf")},
        data={"role": "slides"},
    )
    assert slides.status_code == 201, slides.text
    gone = add(ada, {"title": "Gone"})
    upload(ada, gone, b"%PDF-1.7\n" + b"g" * 3000)
    file = ada.get(f"/api/items/{gone}").json()["versions"][0]["files"][0]["id"]
    assert ada.delete(f"/api/files/{file}").status_code == 204

    def other_disk(source: object, target: object) -> None:
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(readable.os, "link", other_disk)
    root = tmp_path / "copy"
    report = readable.sync(db, blobs, root, "{title}", links=True)
    assert report.error is None
    # The slides are named after their role; the file in the trash is left out.
    assert sorted(p.name for p in root.glob("*.pdf")) == [
        "Engines (slides).pdf",
        "Engines.pdf",
    ]
    assert (root / "Engines (slides).pdf").read_bytes() == SLIDES


def test_a_copy_where_none_can_be(
    client: TestClient, db: Session, blobs: BlobStore, tmp_path: Path
) -> None:
    (tmp_path / "a file").write_text("")
    report = readable.sync(
        db, blobs, tmp_path / "a file" / "copy", "{title}", links=False
    )
    assert report.error is not None and report.files == 0
    assert readable.last_report(db) == report
