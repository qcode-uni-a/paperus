"""Abstracts for papers whose details have none: OpenAlex's, else the PDF's."""

import uuid

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus import abstracts, authors
from paperus.models import Item
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.pdfs import make_pdf
from tests.people import Person
from tests.test_authors import FakeOpenAlex, paper

WORDS = "We show that hole spins in germanium can be driven electrically " * 5
TEXT = WORDS.strip()


def inverted(text: str) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for place, word in enumerate(text.split()):
        index.setdefault(word, []).append(place)
    return index


def test_openalex_text_again() -> None:
    assert abstracts.from_openalex(inverted(TEXT)) == TEXT
    assert abstracts.from_openalex(inverted("Too short.")) is None
    assert abstracts.from_openalex(None) is None
    assert abstracts.from_openalex({"word": "not places"}) is None


def test_the_paragraph_after_the_heading() -> None:
    lines = [f"line {i} of {TEXT[i * 50 : (i + 1) * 50]}" for i in range(8)]
    body = "\n".join(lines)
    first = f"A Title\nSomebody, Somewhere\nAbstract\n{body}\nI. INTRODUCTION\nMore."
    found = abstracts.from_pages([first])
    assert found is not None
    assert found.startswith("line 0 of") and "INTRODUCTION" not in found
    # On the heading's line; up to the keywords; words broken at a line end.
    # (PDFium reads LaTeX's hyphen at a line end as U+0002.)
    broken = "with a hyph-\nenated word, co\u0002\nherent"
    inline = f"ABSTRACT—{body}\n{broken}\nKeywords: spins"
    found = abstracts.from_pages(["Title", inline])
    assert found is not None and found.endswith("with a hyphenated word, coherent")
    assert abstracts.from_pages(["No heading at all\n" + body]) is None
    assert abstracts.from_pages(["Abstract\nToo short.\nIntroduction"]) is None


def test_crossref_markup_taken_out() -> None:
    jats = (
        "<jats:title>Abstract</jats:title><jats:p>First &amp; <jats:italic>one"
        "</jats:italic>.</jats:p>\n<jats:p>Second.</jats:p>"
    )
    assert abstracts.plain(jats) == "First & one.\n\nSecond."


def test_found_abstracts_fill_gaps_only(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    ada = Person(client, db, "ada")
    doi = "10.1000/spins"
    bare = paper(
        ada, "Bare", "Benito, Mónica", identifiers=[{"scheme": "doi", "value": doi}]
    )
    own = paper(ada, "Own", "Benito, Mónica", abstract="Its own words.")
    lines = ["Hole spins", "Abstract", *[TEXT[i : i + 60] for i in range(0, 300, 60)]]
    for item_id in (bare, own):
        file = ada.post(
            f"/api/items/{item_id}/files",
            files={"upload": ("p.pdf", make_pdf([lines]), "application/pdf")},
        ).json()
        process_file(db, blobs, uuid.UUID(file["id"]))
    db.commit()

    def shown(item_id: str) -> str | None:
        found: str | None = ada.get(f"/api/items/{item_id}").json()["abstract"]
        return found

    # The PDF's, for the paper without one; its own stays.
    from_pdf = shown(bare)
    assert from_pdf is not None and from_pdf.startswith(TEXT[:60])
    assert shown(own) == "Its own words."

    # OpenAlex's replaces the PDF's.
    openalex = FakeOpenAlex()
    openalex.works = {doi: [("Mónica Benito", "A1", None, None)]}
    openalex.abstracts = {doi: inverted("OpenAlex " + TEXT)}
    http = httpx2.Client(transport=httpx2.MockTransport(openalex))
    authors.link_waiting(db)
    authors.check_waiting(db, http)
    db.commit()
    assert shown(bare) == "OpenAlex " + TEXT
    # Removed by hand: none, and none found again.
    ada.client.put(
        f"/api/items/{bare}/overrides",
        json={"abstract": None},
        headers={
            **ada.headers,
            "If-Match": ada.get(f"/api/items/{bare}").headers["ETag"],
        },
    )
    assert shown(bare) is None
    db.expire_all()
    item = db.get(Item, uuid.UUID(bare))
    assert item is not None
    assert not abstracts.take(item, "Another " + TEXT, replace=True)
