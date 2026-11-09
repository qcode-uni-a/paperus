"""Annotations: a person's own, shared per paper with those who may read it."""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.models import File
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.pdfs import make_pdf
from tests.people import Person, group


def upload(person: Person, item_id: str) -> str:
    response = person.post(
        f"/api/items/{item_id}/files",
        files={"upload": ("p.pdf", make_pdf([["One"], ["Two"]]), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    file_id: str = response.json()["id"]
    return file_id


def highlight(**changes: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "kind": "highlight",
        "page_index": 0,
        "position": {"rects": [[72, 700, 200, 712]]},
        "color": "#FFD400",
        "text": "One",
    } | changes


def test_own_shared_and_changed(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    carol = Person(client, db, "carol")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    paper = ada.add("Shared paper", chair["library_id"])
    file = upload(ada, paper["id"])
    url = f"/api/files/{file}/annotations"

    made = ada.post(url, highlight(comment="Key result", tags=["a", " a ", "b"]))
    assert made.status_code == 201, made.text
    mine = made.json()
    assert (mine["color"], mine["tags"], mine["mine"], mine["author"]) == (
        "#ffd400",
        ["a", "b"],
        True,
        "ada",
    )
    # Readers annotate too; each sees only their own at first.
    lower = highlight(position={"rects": [[72, 100, 90, 112]]}, color="#5fb236")
    theirs = bob.post(url, lower).json()
    assert [a["id"] for a in ada.get(url).json()["annotations"]] == [mine["id"]]
    seen = bob.get(url).json()
    assert [a["id"] for a in seen["annotations"]] == [theirs["id"]]
    assert (seen["shared"], seen["can_share"]) == (False, True)
    assert carol.get(url).status_code == 404

    # Shared: Bob sees Ada's, above his on the page (reading order).
    assert ada.put(f"/api/items/{paper['id']}/annotation-sharing", {"shared": True})
    seen = bob.get(url).json()["annotations"]
    assert [(a["id"], a["mine"]) for a in seen] == [
        (mine["id"], False),
        (theirs["id"], True),
    ]
    # Only their person changes or removes them.
    assert (
        bob.patch(f"/api/annotations/{mine['id']}", {"comment": "x"}).status_code == 404
    )
    assert bob.delete(f"/api/annotations/{mine['id']}").status_code == 404
    changed = ada.patch(
        f"/api/annotations/{mine['id']}", {"comment": "", "color": "#2EA8E5"}
    ).json()
    assert (changed["comment"], changed["color"], changed["tags"]) == (
        None,
        "#2ea8e5",
        ["a", "b"],
    )
    # Unshared again; then removed.
    ada.put(f"/api/items/{paper['id']}/annotation-sharing", {"shared": False})
    assert [a["id"] for a in bob.get(url).json()["annotations"]] == [theirs["id"]]
    assert ada.delete(f"/api/annotations/{mine['id']}").status_code == 204
    assert ada.get(url).json()["annotations"] == []


def test_what_is_refused(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Mine")
    file = upload(ada, paper["id"])
    url = f"/api/files/{file}/annotations"
    assert ada.get(url).json()["can_share"] is False
    for wrong in (
        highlight(color="yellow"),
        highlight(position={"rects": [[1, 2, 3]]}),
        highlight(position={"rects": []}),
        highlight(kind="ink", position={"paths": [[1, 2, 3, 4]]}),
        highlight(kind="ink", position={"paths": [[1, 2, 3]], "width": 1}),
        highlight(page_index=-1),
    ):
        assert ada.post(url, wrong).status_code == 422, wrong
    ink = ada.post(
        url,
        highlight(
            kind="ink", text=None, position={"paths": [[1, 2, 3, 4]], "width": 2}
        ),
    )
    assert ink.status_code == 201
    assert (
        ada.post(f"/api/files/{uuid.uuid4()}/annotations", highlight()).status_code
        == 404
    )
    assert ada.patch(f"/api/annotations/{uuid.uuid4()}", {}).status_code == 404
    # Not on a file in the trash.
    ada.delete(f"/api/files/{file}")
    assert ada.post(url, highlight()).status_code == 409


ANNOTATED = {
    0: [
        "/Subtype /Highlight /Rect [70 715 250 735]"
        " /QuadPoints [72 734 240 734 72 716 240 716] /C [1 0.83 0] /Contents (Key)",
        "/Subtype /Ink /Rect [100 100 200 200] /InkList [[100 100 150 150 200 120]]"
        " /C [0 0 1]",
        "/Subtype /FreeText /Rect [300 300 400 330] /Contents (Words)"
        " /DA (/Helv 14 Tf 1 0 0 rg)",
        "/Subtype /FreeText /Rect [300 400 400 430]",
        "/Subtype /Text /Rect [500 700 520 720] /Contents (A note)",
        "/Subtype /Link /Rect [0 0 10 10]",
    ]
}


def test_a_pdfs_own_annotations_taken_in(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "member"})
    paper = ada.add("Marked", chair["library_id"])
    pdf = make_pdf([["Line one of the text here"]], annotations=ANNOTATED)
    file_id = ada.post(
        f"/api/items/{paper['id']}/files",
        files={"upload": ("marked.pdf", pdf, "application/pdf")},
    ).json()["id"]
    process_file(db, blobs, uuid.UUID(file_id))
    db.commit()
    url = f"/api/files/{file_id}/annotations"
    seen = ada.get(url).json()
    found = {a["kind"]: a for a in seen["annotations"]}
    # Words without words, and links, stay in the PDF.
    assert sorted(found) == ["highlight", "ink", "note", "text"]
    assert all(a["imported"] and a["mine"] for a in found.values())
    assert (found["highlight"]["text"], found["highlight"]["comment"]) == (
        "Line one of the text here",
        "Key",
    )
    assert found["highlight"]["position"]["rects"] == [[72.0, 716.0, 240.0, 734.0]]
    assert (found["text"]["text"], found["text"]["color"]) == ("Words", "#ff0000")
    assert found["text"]["position"]["font_size"] == 14
    assert found["ink"]["color"] == "#0000ff"
    assert found["note"]["color"] == "#ffd400"  # none given: yellow
    assert len(seen["hidden_marks"]) == 4
    assert {"page_index": 0, "rect": [70.0, 715.0, 250.0, 735.0]} in seen[
        "hidden_marks"
    ]

    # Others see the file as it is, until the uploader shares.
    assert bob.get(url).json()["hidden_marks"] == []
    ada.put(f"/api/items/{paper['id']}/annotation-sharing", {"shared": True})
    assert len(bob.get(url).json()["hidden_marks"]) == 4
    # Deleted: still left out of the page (not drawn twice, nor back).
    ada.delete(f"/api/annotations/{found['ink']['id']}")
    after = ada.get(url).json()
    assert len(after["annotations"]) == 3 and len(after["hidden_marks"]) == 4
    # Read again: taken in once only.
    assert ada.post(f"/api/files/{file_id}/read-again").status_code == 202
    db.expire_all()
    process_file(db, blobs, uuid.UUID(file_id))
    db.commit()
    assert len(ada.get(url).json()["annotations"]) == 3


def test_pages_without_the_files_own_marks(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("Plain")
    file_id = upload(ada, paper["id"])
    process_file(db, blobs, uuid.UUID(file_id))
    db.commit()
    # Nothing to take in: nothing left out.
    assert ada.get(f"/api/files/{file_id}/annotations").json()["hidden_marks"] == []
    file = db.get(File, uuid.UUID(file_id))
    assert file is not None and file.file_marks == []
