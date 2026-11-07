"""Citation export: BibTeX and CSL-JSON."""

import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.importing import bibtex
from tests.people import Person

ARTICLE: dict[str, Any] = {
    "type": "article-journal",
    "title": "Radar gaps & AI over the Alps: 3-D fields",
    "author": [
        {"family": "Gogh", "given": "Vincent", "non-dropping-particle": "van"},
        {"family": "Müller", "given": "Jörg", "suffix": "Jr."},
        {"literal": "Radar Working Group"},
    ],
    "container-title": "Journal of 100% Weather",
    "issued": {"date-parts": [[2024, 3, 2]]},
    "volume": "12",
    "issue": "4",
    "page": "101-120",
    "DOI": "10.1234/radar",
}


def add(person: Person, metadata: dict[str, Any]) -> str:
    response = person.post("/api/items", json={"metadata": metadata})
    assert response.status_code == 201, response.text
    item_id: str = response.json()["id"]
    return item_id


def test_bibtex_entry(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    item = add(ada, ARTICLE)
    ada.post(f"/api/items/{item}/tags", json={"name": "radar"})
    response = ada.get("/api/citations", params={"item": item})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-bibtex")
    assert "van_gogh_radar_2024.bib" in response.headers["content-disposition"]
    # As Zotero writes it: its key form, field order and case protection.
    assert response.text == (
        "@article{van_gogh_radar_2024,\n"
        "\ttitle = {Radar gaps \\& {AI} over the {Alps}: 3-{D} fields},\n"
        "\tvolume = {12},\n"
        "\tdoi = {10.1234/radar},\n"
        "\tnumber = {4},\n"
        "\tjournal = {Journal of 100\\% Weather},\n"
        "\tauthor = {van Gogh, Vincent and Müller, Jr., Jörg and"
        " {Radar Working Group}},\n"
        "\tmonth = mar,\n"
        "\tyear = {2024},\n"
        "\tkeywords = {radar},\n"
        "\tpages = {101--120},\n"
        "}\n"
    )


def test_keys_types_and_csl_json(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    first = add(ada, {**ARTICLE, "type": "paper-conference"})
    second = add(ada, ARTICLE)
    own = add(ada, {**ARTICLE, "citation-key": "vg24", "type": "thesis"})
    preprint = add(
        ada,
        {
            "type": "article",
            "title": "The diffusion of rain",
            "author": [{"family": "Lovelace", "given": "Ada"}],
            "issued": {"date-parts": [[2026]]},
            "DOI": "10.48550/arXiv.2611.00001",
        },
    )
    text = ada.get(
        "/api/citations", params={"item": [first, second, own, preprint]}
    ).text
    assert "@inproceedings{van_gogh_radar_2024,\n" in text
    assert "\tbooktitle = {Journal of 100\\% {Weather}},\n" in text
    assert "@article{van_gogh_radar_2024-1,\n" in text  # same key: a suffix
    assert "@phdthesis{vg24,\n" in text  # the paper's own key (Better BibTeX)
    assert "@misc{lovelace_diffusion_2026,\n" in text
    assert "\teprint = {2611.00001},\n\tarchiveprefix = {arXiv},\n" in text

    exported = json.loads(
        ada.get("/api/citations", params={"format": "csl-json", "item": first}).text
    )
    assert exported == [
        {
            **ARTICLE,
            "type": "paper-conference",
            "id": "van_gogh_radar_2024",
            "citation-key": "van_gogh_radar_2024",
        }
    ]


def test_collections_and_access(client: TestClient, db: Session) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    inside = add(ada, ARTICLE)
    add(ada, {"title": "Elsewhere"})
    trashed = add(ada, {"title": "Gone"})
    ada.delete(f"/api/items/{trashed}")
    shelf = ada.post("/api/collections", json={"name": "Radar shelf"}).json()["id"]
    sub = ada.post("/api/collections", json={"name": "Sub", "parent_id": shelf}).json()[
        "id"
    ]
    ada.post(f"/api/collections/{sub}/items", json={"item_ids": [inside]})

    response = ada.get("/api/citations", params={"collection": shelf, "download": True})
    assert response.text.count("@") == 1 and "van_gogh_radar_2024" in response.text
    assert response.headers["content-disposition"].startswith("attachment")
    assert "Radar-shelf.bib" in response.headers["content-disposition"]
    assert (
        ada.get("/api/citations", params={"collection": shelf, "nested": False}).text
        == ""
    )
    everything = ada.get("/api/citations").text
    assert everything.count("@") == 2 and "Gone" not in everything
    # Others get nothing of it.
    assert bob.get("/api/citations").text == ""
    assert bob.get("/api/citations", params={"item": inside}).text == ""
    assert bob.get("/api/citations", params={"collection": shelf}).status_code == 404


def test_odd_metadata_and_keys(client: TestClient, db: Session) -> None:
    """Imports and manual edits can hold any JSON: the export copes, and
    every key is one BibTeX takes, once."""
    ada = Person(client, db, "ada")
    odd = add(
        ada,
        {
            "type": "article",
            "title": "Odd",
            "author": ["Smith, J", {"given": "Plato"}],
            "issued": "2020",
            "accessed": {"date-parts": [[2020, "May"]]},
            "URL": "https://example.org/{x",
            "citation-key": "Smith 2020, x",
        },
    )
    zero = add(ada, {"title": "Zero month", "issued": {"date-parts": [[2021, 0]]}})
    twice = [
        add(ada, {"title": f"Same key {n}", "citation-key": "dup"}) for n in (1, 2)
    ]
    response = ada.get("/api/citations", params={"item": [odd, zero, *twice]})
    assert response.status_code == 200, response.text
    text = response.text
    assert "@misc{Smith2020x,\n" in text
    assert "\tauthor = {{Smith, J} and {Plato}},\n" in text
    assert "\tyear = {2020},\n" in text
    assert "url = {https://example.org/%7Bx}" in text
    assert "month =" not in text  # month 0 is no month
    assert "@misc{dup,\n" in text and "@misc{dup-1,\n" in text
    assert ada.get("/api/citations", params={"format": "csl-json"}).status_code == 200


def test_theses_reports_and_odd_shapes(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    thesis = add(
        ada,
        {
            "type": "thesis",
            "genre": "Master's thesis",
            "title": "Engines",
            "publisher": "Uni",
            "author": "Ada Lovelace",
            "issued": {"date-parts": [[1843, "March"]]},
        },
    )
    report = add(
        ada,
        {
            "type": "report",
            "genre": "Technical report",
            "title": "Rain",
            "publisher": "Weather Office",
            "ISBN": [],
        },
    )
    text = ada.get("/api/citations", params={"item": [thesis, report]}).text
    assert "@mastersthesis{" in text
    assert "\tschool = {Uni},\n" in text
    assert "\tauthor = {{Ada Lovelace}},\n" in text
    assert "month =" not in text  # "March" is no month number
    assert "\tyear = {1843},\n" in text
    assert "@techreport{" in text
    assert "\tinstitution = {Weather Office},\n" in text
    assert "\ttype = {Technical report},\n" in text
    assert "isbn" not in text


def test_bibtex_reads_back(client: TestClient, db: Session) -> None:
    """LaTeX's special characters and a brace without its pair: the .bib
    stays readable and gives the title back."""
    ada = Person(client, db, "ada")
    title = "Half {open, $<x>|y^2$ ~ 50% & #1_a\\b"
    item = add(ada, {"type": "article-journal", "title": title})
    text = ada.get("/api/citations", params={"item": item}).text
    assert "{\\textbraceleft}" in text
    export = bibtex.read(text)
    assert export.problems == []
    assert export.papers[0].csl["title"] == title
