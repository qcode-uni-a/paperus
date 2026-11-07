"""Authors as people: linked by ids or the same full name, kept apart after
a split, merged, assigned by hand; seen only through one's papers."""

import uuid
from typing import Any, cast

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus import authors, jobs
from paperus.config import Settings
from paperus.models import Author, Authorship, Item
from paperus.system import load_config, save_config
from tests.people import Person
from tests.test_jobs import worker  # noqa: F401 (fixture)


def paper(person: Person, title: str, *names: str, **fields: Any) -> str:  # noqa: ANN401
    """A paper by these authors ("Family, Given", or a dict as in CSL)."""
    people: list[dict[str, str]] = []
    for name in names:
        family, _, given = name.partition(",")
        people.append(
            {"family": family.strip(), "given": given.strip()}
            if given
            else {"literal": family.strip()}
        )
    identifiers = fields.pop("identifiers", [])
    response = person.post(
        "/api/items",
        json={
            "metadata": {"title": title, "author": people, **fields},
            "identifiers": identifiers,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def people(db: Session, item_id: str) -> list[uuid.UUID | None]:
    db.expire_all()
    item = db.get(Item, uuid.UUID(item_id))
    assert item is not None
    return [a.author_id for a in item.authorships]


def test_names_and_ids() -> None:
    assert authors.fold("Hernández-Mínguez, Alberto") == "hernandez minguez alberto"
    assert authors.fold("  Mónica   BENITO ") == "monica benito"
    assert authors.orcid_of("https://orcid.org/0000-0002-1825-009x") == (
        "0000-0002-1825-009X"
    )
    assert authors.orcid_of(None) is None
    written = authors.written_authors(
        {
            "author": [
                {"family": "Benito", "given": "Mónica", "ORCID": "0000-0001-2345-6789"},
                {"literal": "LIGO Collaboration"},
                {"given": "nobody"},
                "not a person",
            ]
        }
    )
    assert [(w.written, w.shown, w.key, w.orcid) for w in written] == [
        ("Benito, Mónica", "Mónica Benito", "monica benito", "0000-0001-2345-6789"),
        ("LIGO Collaboration", "LIGO Collaboration", "ligo collaboration", None),
    ]


def test_the_same_full_name_is_one_person(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    one = paper(ada, "One", "Benito, Mónica", "Platero, Gloria")
    two = paper(ada, "Two", "benito, Monica")
    three = paper(ada, "Three", "Benito, M.")
    assert authors.link_waiting(db) == 3
    assert authors.link_waiting(db) == 0  # nothing waits any more
    [benito, platero] = people(db, one)
    assert people(db, two) == [benito]
    # Initials are another name: not joined.
    [initials] = people(db, three)
    assert initials not in (benito, platero)
    person = db.get(Author, benito)
    assert person is not None and person.name == "Mónica Benito"  # the accents

    # The website shows each author's person; the list filters by one.
    item = ada.get(f"/api/items/{one}").json()
    assert item["author_ids"] == [str(benito), str(platero)]
    titles = ada.titles(author_id=str(benito))
    assert titles == ["One", "Two"]
    # Changed names wait to be linked again: no ids meanwhile.
    etag = ada.get(f"/api/items/{two}").headers["ETag"]
    response = client.put(
        f"/api/items/{two}/overrides",
        json={"author": [{"family": "Platero", "given": "Gloria"}]},
        headers={**ada.headers, "If-Match": etag},
    )
    assert response.status_code == 200, response.text
    assert ada.get(f"/api/items/{two}").json()["author_ids"] is None
    authors.link_waiting(db)
    assert people(db, two) == [platero]


def test_ids_win_over_names(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    orcid = "0000-0001-2345-6789"
    first = paper(ada, "First", "Benito, Mónica")
    by_id = ada.post(
        "/api/items",
        json={"metadata": {"title": "With iD", "author": [
            {"family": "Benito", "given": "M.", "ORCID": f"https://orcid.org/{orcid}"}
        ]}},
    ).json()["id"]  # fmt: skip
    other_id = ada.post(
        "/api/items",
        json={"metadata": {"title": "Other iD", "author": [
            {"family": "Benito", "given": "Mónica", "ORCID": "0000-0009-8765-4321"}
        ]}},
    ).json()["id"]  # fmt: skip
    authors.link_waiting(db)
    [named] = people(db, first)
    [with_id] = people(db, by_id)
    [other] = people(db, other_id)
    # "M. Benito" with an iD is a person of their own (initials); the full
    # name with an iD is the person of that name, who now has the iD.
    assert named == other and with_id not in (None, named)
    record = db.get(Author, with_id)
    assert record is not None and record.orcid == orcid
    # Yet another iD under the full name: someone else (iDs never meet).
    third = ada.post(
        "/api/items",
        json={"metadata": {"title": "Third iD", "author": [
            {"family": "Benito", "given": "Mónica", "ORCID": "0000-0005-5555-5555"}
        ]}},
    ).json()["id"]  # fmt: skip
    authors.link_waiting(db)
    assert people(db, third)[0] not in (named, with_id, None)
    # The same iD later, under the full name: the person with that iD.
    again = ada.post(
        "/api/items",
        json={"metadata": {"title": "Again", "author": [
            {"family": "Benito", "given": "Mónica", "ORCID": orcid}
        ]}},
    ).json()["id"]  # fmt: skip
    authors.link_waiting(db)
    assert people(db, again) == [with_id]


def test_two_people_of_one_name_stay_apart(client: TestClient, db: Session) -> None:
    """The plan's case: two real Mónica Benitos."""
    ada = Person(client, db, "ada")
    a1 = paper(ada, "Spin qubits", "Benito, Mónica", "Platero, Gloria")
    a2 = paper(ada, "Driven dots", "Benito, Mónica", "Platero, Gloria")
    b1 = paper(ada, "Proteins", "Benito, Mónica", "Smith, Jane")
    authors.link_waiting(db)
    [benito, platero] = people(db, a1)
    assert people(db, b1)[0] == benito  # one person, for now

    # Split: the protein paper is by someone else.
    response = ada.post(f"/api/authors/{benito}/split", {"item_ids": [b1]})
    assert response.status_code == 201, response.text
    biologist = uuid.UUID(response.json()["id"])
    assert people(db, b1)[0] == biologist and people(db, a2)[0] == benito
    assert (
        ada.post(f"/api/authors/{benito}/split", {"item_ids": [b1]}).status_code == 422
    )

    # Linked again from scratch (as after a re-import): the split holds.
    db.query(Item).update({Item.authors_linked: None})
    db.commit()
    authors.link_waiting(db)
    assert people(db, b1)[0] == biologist and people(db, a1)[0] == benito

    # New papers go to the one with the same co-authors; alone: to check.
    physics = paper(ada, "More qubits", "Benito, Mónica", "Platero, Gloria")
    biology = paper(ada, "More proteins", "Smith, Jane", "Benito, Mónica")
    unclear = paper(ada, "Alone", "Benito, Mónica")
    authors.link_waiting(db)
    assert people(db, physics) == [benito, platero]
    assert people(db, biology)[1] == biologist
    assert people(db, unclear) == [None]

    [check] = ada.get("/api/authors-to-check").json()
    assert check["item"]["id"] == unclear and check["written"] == "Benito, Mónica"
    assert {c["id"] for c in check["candidates"]} == {str(benito), str(biologist)}
    # Decided by hand, kept by later passes.
    url = f"/api/items/{unclear}/authors/1"
    assert ada.put(url, {"author_id": str(biologist)}).json()["id"] == str(biologist)
    db.query(Item).update({Item.authors_linked: None})
    db.commit()
    authors.link_waiting(db)
    assert people(db, unclear) == [biologist]
    assert ada.get("/api/authors-to-check").json() == []
    # Someone new of that name.
    made = ada.put(url, {"author_id": None}).json()
    assert made["id"] not in (str(benito), str(biologist)) and made["papers"] == 1
    assert (
        ada.put(f"/api/items/{unclear}/authors/9", {"author_id": None}).status_code
        == 404
    )

    # Each sees the other as a namesake.
    page = ada.get(f"/api/authors/{benito}").json()
    assert {n["id"] for n in page["namesakes"]} >= {str(biologist)}
    assert [c["name"] for c in page["coauthors"]] == ["Gloria Platero"]


def test_merge(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    full = paper(ada, "Full", "Benito, Mónica")
    short = paper(ada, "Short", "Benito, M.")
    authors.link_waiting(db)
    [keep] = people(db, full)
    [other] = people(db, short)
    record = db.get(Author, other)
    assert record is not None
    record.orcid = "0000-0001-2345-6789"
    db.commit()
    assert (
        ada.post(f"/api/authors/{keep}/merge", {"other_id": str(keep)}).status_code
        == 409
    )
    response = ada.post(f"/api/authors/{keep}/merge", {"other_id": str(other)})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": str(keep),
        "name": "Mónica Benito",
        "papers": 2,
        "orcid": "0000-0001-2345-6789",
    }
    db.expire_all()
    assert db.get(Author, other) is None
    page = ada.get(f"/api/authors/{keep}").json()
    assert page["spellings"] == ["Benito, Mónica", "Benito, M."] or page[
        "spellings"
    ] == ["Benito, M.", "Benito, Mónica"]
    # Two different iDs are two people.
    third = paper(ada, "Third", "Benito, María")
    authors.link_waiting(db)
    [maria] = people(db, third)
    record = db.get(Author, maria)
    assert record is not None
    record.orcid = "0000-0009-8765-4321"
    db.commit()
    refused = ada.post(f"/api/authors/{keep}/merge", {"other_id": str(maria)})
    assert refused.status_code == 409 and "ORCID" in refused.text


def test_seen_only_through_ones_papers(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    bob = Person(client, db, "bob")
    paper(ada, "Private", "Secret, Sam", "Public, Pat")
    paper(bob, "Bob's", "Public, Pat")
    authors.link_waiting(db)
    sam = db.scalar(select(Author).where(Author.key == "sam secret"))
    pat = db.scalar(select(Author).where(Author.key == "pat public"))
    assert sam is not None and pat is not None

    def names(person: Person, **params: str) -> list[tuple[str, int]]:
        response = person.get("/api/authors", params=params)
        assert response.status_code == 200, response.text
        assert response.headers["X-Total-Count"] == str(len(response.json()))
        return [(a["name"], a["papers"]) for a in response.json()]

    assert names(ada) == [("Pat Public", 1), ("Sam Secret", 1)]
    assert names(bob) == [("Pat Public", 1)]
    assert names(ada, q="SÁM") == [("Sam Secret", 1)]
    assert names(ada, sort="name") == [("Pat Public", 1), ("Sam Secret", 1)]
    assert bob.get(f"/api/authors/{sam.id}").status_code == 404
    assert bob.get(f"/api/authors/{pat.id}").json()["coauthors"] == []
    assert ada.get(f"/api/authors/{pat.id}").json()["coauthors"][0]["name"] == (
        "Sam Secret"
    )
    assert bob.post(f"/api/authors/{sam.id}/split", {"item_ids": []}).status_code == 422


def test_where_they_were_and_people_without_papers(
    client: TestClient, db: Session
) -> None:
    ada = Person(client, db, "ada")
    old = paper(ada, "Old", "Benito, Mónica", issued={"date-parts": [[2016]]})
    new = paper(ada, "New", "Benito, Mónica", issued={"date-parts": [[2024]]})
    newer = paper(ada, "Newer", "Benito, Mónica", issued={"date-parts": [[2025]]})
    authors.link_waiting(db)
    [benito] = people(db, old)
    for item_id, place in ((old, "UAM Madrid"), (new, "Augsburg"), (newer, "Augsburg")):
        authorship = db.get(Authorship, (uuid.UUID(item_id), 1))
        assert authorship is not None
        authorship.affiliation = place
    db.commit()
    page = ada.get(f"/api/authors/{benito}").json()
    assert page["affiliations"] == [
        {"name": "Augsburg", "first_year": 2024, "last_year": 2025, "papers": 2},
        {"name": "UAM Madrid", "first_year": 2016, "last_year": 2016, "papers": 1},
    ]
    # In the trash: not shown; emptied: the person goes too.
    for item_id in (old, new, newer):
        assert ada.delete(f"/api/items/{item_id}").status_code in (200, 204)
    assert ada.get(f"/api/authors/{benito}").status_code == 404
    assert ada.delete("/api/trash").status_code in (200, 204)
    authors.link_waiting(db)
    db.expire_all()
    assert db.get(Author, benito) is None


def test_the_job(client: TestClient, db: Session, worker: None) -> None:  # noqa: F811
    ada = Person(client, db, "ada")
    item_id = paper(ada, "Queued", "Benito, Mónica")
    jobs.link_authors(cast(Any, None), 0)
    assert people(db, item_id) != [None]
    jobs.link_authors(cast(Any, None), 0)  # nothing waiting: quiet
    # An administrator can start it now.
    root = Person(client, db, "root", admin=True)
    assert root.post("/api/admin/jobs/authors").status_code == 202


@pytest.mark.parametrize("names", [(), ("LIGO Collaboration",)])
def test_papers_without_people(
    client: TestClient, db: Session, names: tuple[str, ...]
) -> None:
    ada = Person(client, db, "ada")
    item_id = paper(ada, "Group work", *names)
    authors.link_waiting(db)
    assert len(people(db, item_id)) == len(names)
    assert ada.get(f"/api/items/{item_id}").json()["author_ids"] == [
        str(i) for i in people(db, item_id)
    ]


class FakeOpenAlex:
    """OpenAlex's works by DOI: each a list of (display name, id, ORCID,
    institution)."""

    def __init__(self) -> None:
        self.works: dict[str, list[tuple[str, str, str | None, str | None]]] = {}
        self.status = 200
        self.asked: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        assert request.url.host == "api.openalex.org"
        if self.status != 200:
            return httpx2.Response(self.status)
        dois = request.url.params["filter"].removeprefix("doi:").split("|")
        self.asked += dois
        results = [
            {
                "doi": f"https://doi.org/{doi}",
                "authorships": [
                    {
                        "author": {
                            "display_name": name,
                            "id": f"https://openalex.org/{openalex}",
                            "orcid": f"https://orcid.org/{orcid}" if orcid else None,
                        },
                        "institutions": [{"display_name": place}] if place else [],
                        "raw_affiliation_strings": ["Somewhere, raw"],
                    }
                    for name, openalex, orcid, place in self.works[doi]
                ],
            }
            for doi in dois
            if doi in self.works
        ]
        return httpx2.Response(200, json={"results": results})


def with_doi(person: Person, title: str, doi: str, *names: str) -> str:
    return paper(person, title, *names, identifiers=[{"scheme": "doi", "value": doi}])


def test_who_they_are_from_openalex(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    openalex = FakeOpenAlex()
    http = httpx2.Client(transport=httpx2.MockTransport(openalex))
    orcid = "0000-0001-2345-6789"
    full = with_doi(ada, "Full", "10.1000/full", "Benito, Mónica", "Platero, Gloria")
    short = with_doi(ada, "Short", "10.1000/short", "Benito, M.")
    other = with_doi(ada, "Proteins", "10.1000/proteins", "Benito, Mónica")
    hand = with_doi(ada, "By hand", "10.1000/hand", "Benito, Mónica")
    unknown = with_doi(ada, "Unknown to OpenAlex", "10.1000/unknown", "Nobody, Ned")
    without = paper(ada, "Without a DOI", "Benito, Mónica")
    openalex.works = {
        "10.1000/full": [
            ("Mónica Benito", "A1", orcid, "Universität Augsburg"),
            ("Gloria Platero", "A2", None, None),
        ],
        "10.1000/short": [("M. Benito", "A1", orcid, None)],
        "10.1000/proteins": [("Mónica Benito", "A9", None, "Universidad de Sevilla")],
        "10.1000/hand": [("Mónica Benito", "A9", None, None)],
    }
    authors.link_waiting(db)
    [before] = people(db, hand)
    ada.put(f"/api/items/{hand}/authors/1", {"author_id": str(before)})

    assert authors.check_waiting(db, http, contact_email="lab@example.org") == 4
    assert sorted(openalex.asked) == [
        f"10.1000/{name}" for name in ("full", "hand", "proteins", "short", "unknown")
    ]
    authors.link_waiting(db)
    [benito, platero] = people(db, full)
    # The same iD: initials and the full name are one person.
    assert people(db, short) == [benito]
    record = db.get(Author, benito)
    assert record is not None and (record.orcid, record.openalex_id) == (orcid, "A1")
    # Another OpenAlex id: another person of the same name; by hand stays.
    [biologist] = people(db, other)
    assert biologist not in (benito, None)
    assert people(db, hand) == [before]
    assert people(db, unknown) != [None]
    # Where they were, per paper (an institution, else the raw string).
    page = ada.get(f"/api/authors/{benito}").json()
    assert page["affiliations"][0]["name"] == "Universität Augsburg"
    assert page["openalex_id"] == "A1"
    assert ada.get(f"/api/authors/{platero}").json()["affiliations"][0]["name"] == (
        "Somewhere, raw"
    )
    # Each paper once; papers without a DOI are not asked about.
    openalex.asked.clear()
    assert authors.check_waiting(db, http) == 0
    assert openalex.asked == []
    db.expire_all()
    item = db.get(Item, uuid.UUID(without))
    assert item is not None and item.authors_checked_at is None
    # Two OpenAlex profiles of one person may be merged; two ORCIDs not.
    merged = ada.post(f"/api/authors/{biologist}/merge", {"other_id": str(benito)})
    assert merged.status_code == 200, merged.text


def test_openalex_unreachable(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    openalex = FakeOpenAlex()
    openalex.status = 503
    http = httpx2.Client(transport=httpx2.MockTransport(openalex))
    item_id = with_doi(ada, "Down", "10.1000/down", "Benito, Mónica")
    authors.link_waiting(db)
    assert authors.check_waiting(db, http) == 0
    [person] = people(db, item_id)
    record = db.get(Author, person)
    assert record is not None and record.openalex_id is None


def test_the_hourly_lookup(
    client: TestClient,
    db: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    worker: None,  # noqa: F811
) -> None:
    ada = Person(client, db, "ada")
    openalex = FakeOpenAlex()
    openalex.works["10.1000/x"] = [("Mónica Benito", "A1", None, None)]
    item_id = with_doi(ada, "X", "10.1000/x", "Benito, Mónica")
    context = jobs._worker_context()
    monkeypatch.setattr(
        context, "http", httpx2.Client(transport=httpx2.MockTransport(openalex))
    )
    config = load_config(db, settings)
    config.find_authors = False
    save_config(db, config)
    db.commit()
    jobs.look_up_authors(cast(Any, None), 0)
    assert openalex.asked == []
    config.find_authors = True
    save_config(db, config)
    db.commit()
    jobs.link_authors(cast(Any, None), 0)
    jobs.look_up_authors(cast(Any, None), 0)
    assert openalex.asked == ["10.1000/x"]
    [person] = people(db, item_id)
    record = db.get(Author, person)
    assert record is not None and record.openalex_id == "A1"


def test_probably_the_same(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    full = paper(ada, "Full", "Benito, Mónica", "Platero, Gloria")
    short = paper(ada, "Short", "Benito, M.", "Platero, Gloria")
    maria = paper(ada, "María", "Benito, María")
    initials = paper(ada, "Initials", "Benito, M. F.")
    authors.link_waiting(db)
    [monica, platero] = people(db, full)
    [m, _] = people(db, short)
    [other] = people(db, maria)
    [mf] = people(db, initials)

    def pairs() -> list[tuple[set[str], int]]:
        response = ada.get("/api/authors-suggestions")
        assert response.status_code == 200, response.text
        return [
            ({p["one"]["name"], p["other"]["name"]}, p["shared"])
            for p in response.json()
        ]

    found = pairs()
    # Co-authors in common first; "Mónica" and "María" never.
    assert found[0] == ({"Mónica Benito", "M. Benito"}, 1)
    assert {"Mónica Benito", "María Benito"} not in [names for names, _ in found]
    assert ({"M. Benito", "M. F. Benito"}, 0) in found
    assert ({"María Benito", "M. Benito"}, 0) in found
    # Different people: not suggested again.
    response = ada.post(f"/api/authors/{m}/apart", {"other_id": str(mf)})
    assert response.status_code == 204
    assert ({"M. Benito", "M. F. Benito"}, 0) not in pairs()
    assert ada.post(f"/api/authors/{m}/apart", {"other_id": str(m)}).status_code == 422
    # Merged, "M." is one of Mónica's spellings: it no longer fits María.
    assert (
        ada.post(f"/api/authors/{monica}/merge", {"other_id": str(m)}).status_code
        == 200
    )
    assert {"Mónica Benito", "María Benito"} not in [names for names, _ in pairs()]
    m = monica
    # Two ORCID iDs: not suggested.
    for person, orcid in ((m, "0000-0001-0000-0001"), (other, "0000-0002-0000-0002")):
        record = db.get(Author, person)
        assert record is not None
        record.orcid = orcid
    db.commit()
    assert ({"María Benito", "Mónica Benito"}, 0) not in pairs()
    assert platero
