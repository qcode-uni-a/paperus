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
from paperus.models import Author, AuthorChange, Authorship, Item
from paperus.system import load_config, save_config
from tests.people import Person, group
from tests.test_jobs import worker  # noqa: F401 (fixture)
from tests.test_mcp import ALL, Assistant, ToolFailed, token


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
    # The number next to Manage → Authors in the menu.
    assert ada.get("/api/manage/counts").json()["authors_to_check"] == 1
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
        "written": "Benito, Mónica",
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


def test_undoing_a_merge_gives_the_old_name_back(
    client: TestClient, db: Session
) -> None:
    ada = Person(client, db, "ada")
    full = paper(ada, "Full", "Benito, Mónica")
    short = paper(ada, "Short", "Benito, M.")
    authors.link_waiting(db)
    [other] = people(db, full)
    [keep] = people(db, short)
    response = ada.post(f"/api/authors/{keep}/merge", {"other_id": str(other)})
    assert response.json()["name"] == "Mónica Benito"  # the fuller spelling
    [change] = ada.get(f"/api/authors/{keep}").json()["changes"]
    assert change["renamed_from"] == "M. Benito"
    assert ada.post(f"/api/author-changes/{change['id']}/undo").status_code == 200
    db.expire_all()
    record = db.get(Author, keep)
    assert record is not None and record.name == "M. Benito"


def test_a_merge_keeps_the_fuller_name_and_finds_every_spelling(
    client: TestClient, db: Session
) -> None:
    ada = Person(client, db, "ada")
    short = paper(ada, "Short", "Pioro-Ladrière, M.")
    full = paper(ada, "Full", "Pioro-Ladrière, Michel")
    authors.link_waiting(db)
    [keep] = people(db, short)
    [other] = people(db, full)
    response = ada.post(f"/api/authors/{keep}/merge", {"other_id": str(other)})
    assert response.json()["name"] == "Michel Pioro-Ladrière"
    for words in ("michel", "m pioro", "ladriere"):
        found = ada.get("/api/authors", params={"q": words}).json()
        assert [a["id"] for a in found] == [str(keep)], words
    # Given names that do not fit keep the name as it was.
    qian = paper(ada, "Qian's", "Dong, Qian")
    shi = paper(ada, "Shi-Hai's", "Dong, Shi-Hai")
    authors.link_waiting(db)
    [first] = people(db, qian)
    [second] = people(db, shi)
    merged = ada.post(f"/api/authors/{first}/merge", {"other_id": str(second)})
    assert merged.json()["name"] == "Qian Dong"


def test_names_written_as_the_person_chooses(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper(ada, "One", "Zeller, Anna", "Albers, Zoe", "Mitte")
    authors.link_waiting(db)
    assert ada.get("/api/auth/me").json()["name_format"] == "family-given"

    def by_name() -> list[tuple[str, str]]:
        found = ada.get("/api/authors", params={"sort": "name"}).json()
        return [(a["name"], a["written"]) for a in found]

    # Family names first: sorted by them.
    assert by_name() == [
        ("Zoe Albers", "Albers, Zoe"),
        ("Mitte", "Mitte"),
        ("Anna Zeller", "Zeller, Anna"),
    ]
    assert (
        ada.put("/api/auth/name-format", {"name_format": "given-family"}).status_code
        == 204
    )
    assert ada.get("/api/auth/me").json()["name_format"] == "given-family"
    assert [name for name, _ in by_name()] == ["Anna Zeller", "Mitte", "Zoe Albers"]
    assert ada.put("/api/auth/name-format", {"name_format": "x"}).status_code == 422


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
    counts = ada.get("/api/manage/counts").json()
    assert counts["authors_likely"] == len(found)
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


def test_smart_collections_by_author(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    qubits = paper(ada, "Qubits", "Benito, Mónica", "Platero, Gloria")
    paper(ada, "Proteins", "Smith, Jane")
    paper(ada, "Lone", "Platero, Gloria")
    paper(ada, "Dots", "Benito, Mónica")
    authors.link_waiting(db)
    [benito, platero] = people(db, qubits)
    response = ada.post(
        "/api/collections",
        json={"name": "Mónica's", "rules": {"authors": [str(benito)]}},
    )
    assert response.status_code == 201, response.text
    assert ada.titles(collection=response.json()["id"]) == ["Dots", "Qubits"]
    # In the list: by any of several people.
    listed = ada.get("/api/items", params={"author_id": [str(benito), str(platero)]})
    assert sorted(i["title"] for i in listed.json()) == ["Dots", "Lone", "Qubits"]


def test_assistants_find_authors(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    qubits = paper(ada, "Qubits", "Benito, Mónica", "Platero, Gloria")
    paper(ada, "Dots", "Benito, M.")
    authors.link_waiting(db)
    [benito, platero] = people(db, qubits)
    ai = Assistant(client, token(ada, *ALL))
    found = ai.call("find_authors", name="benito")
    assert sorted((f["name"], f["papers"]) for f in found) == [
        ("M. Benito", 1),
        ("Mónica Benito", 1),
    ]
    person = ai.call("get_author", author_id=str(benito))
    assert person["name"] == "Mónica Benito"
    assert [p["title"] for p in person["newest_papers"]] == ["Qubits"]
    assert [c["name"] for c in person["coauthors"]] == ["Gloria Platero"]
    with pytest.raises(ToolFailed, match="No such author"):
        ai.call("get_author", author_id=str(uuid.uuid4()))
    listed = ai.call("list_documents", author_id=str(platero))["papers"]
    assert [p["title"] for p in listed] == ["Qubits"]
    document = ai.call("get_document", paper_id=qubits)
    assert document["people"] == [
        # (Empty fields are left out.)
        {"name": "Benito, Mónica", "author_id": str(benito)},
        {"name": "Platero, Gloria", "author_id": str(platero)},
    ]


def test_who_may_fix_authors(client: TestClient, db: Session) -> None:
    """Author records are shared: fixing one needs a paper of theirs that is
    one's own to change, not only to read."""
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    library = ada.libraries()["Chair"]["id"]
    added = ada.post(
        "/api/items",
        json={
            "metadata": {
                "title": "Shared",
                "author": [{"family": "Benito", "given": "M."}],
            },
            "library_id": library,
        },
    )
    shared = added.json()["id"]
    mine = paper(ada, "Mine", "Benito, Mónica")
    authors.link_waiting(db)
    [m] = people(db, shared)
    [monica] = people(db, mine)
    assert bob.get(f"/api/authors/{m}").json()["may_change"] is False
    assert ada.get(f"/api/authors/{m}").json()["may_change"] is True
    # Bob only reads the group's paper.
    for url, body in (
        (f"/api/authors/{m}/split", {"item_ids": [shared]}),
        (f"/api/authors/{m}/apart", {"other_id": str(m)}),
    ):
        assert bob.post(url, body).status_code in (403, 422)
    assert (
        bob.put(f"/api/items/{shared}/authors/1", {"author_id": None}).status_code
        == 403
    )
    # He cannot see Ada's own Mónica; were she his too, still not his to change.
    assert (
        bob.post(f"/api/authors/{m}/merge", {"other_id": str(monica)}).status_code
        == 404
    )
    bobs = paper(bob, "Bob's", "Benito, Mónica")
    authors.link_waiting(db)
    assert people(db, bobs) == [monica]
    # Suggested to the one who may merge them, not to him.
    assert len(ada.get("/api/authors-suggestions").json()) == 1
    assert bob.get("/api/authors-suggestions").json() == []
    refused = bob.post(f"/api/authors/{monica}/merge", {"other_id": str(m)})
    assert refused.status_code == 403 and "M. Benito" in refused.text
    assert (
        bob.post(f"/api/authors/{monica}/apart", {"other_id": str(m)}).status_code
        == 403
    )


def test_fixes_are_logged_and_undone(client: TestClient, db: Session) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    first = paper(ada, "First", "Benito, Mónica", "Platero, Gloria")
    second = paper(ada, "Second", "Benito, Mónica")
    short = paper(ada, "Short", "Benito, M.")
    authors.link_waiting(db)
    [monica, _] = people(db, first)
    [m] = people(db, short)
    assert monica is not None and m is not None

    def changes(author: uuid.UUID, person: Person = ada) -> list[dict[str, Any]]:
        response = person.get(f"/api/authors/{author}")
        assert response.status_code == 200, response.text
        return [
            {k: c[k] for k in ("kind", "by_you", "other_name", "other_id", "papers")}
            | {"undone": c["undone"], "may_undo": c["may_undo"], "id": c["id"]}
            for c in response.json()["changes"]
        ]

    def undo(change: dict[str, Any]) -> int:
        return ada.post(f"/api/author-changes/{change['id']}/undo").status_code

    # A merge, logged, and undone: "M. Benito" is someone again.
    ada.post(f"/api/authors/{monica}/merge", {"other_id": str(m)})
    [merged] = changes(monica)
    assert {k: merged[k] for k in merged if k != "id"} == {
        "kind": "merge",
        "by_you": True,
        "other_name": "M. Benito",
        "other_id": None,
        "papers": 1,
        "undone": False,
        "may_undo": True,
    }
    assert (
        ada.get(f"/api/authors/{monica}").json()["changes"][0]["renamed_from"] is None
    )
    assert undo(merged) == 200
    [back] = people(db, short)
    assert back is not None and back != monica
    assert authors.are_apart(db, monica, back)
    assert changes(monica)[0]["undone"] and undo(merged) == 409

    # A split, seen from both people, undone from the one split.
    response = ada.post(f"/api/authors/{monica}/split", {"item_ids": [second]})
    other = uuid.UUID(response.json()["id"])
    [split, _] = changes(monica)
    assert (split["kind"], split["other_id"], split["papers"]) == (
        "split",
        str(other),
        1,
    )
    [seen] = changes(other)
    assert (seen["other_id"], seen["may_undo"]) == (str(monica), False)
    assert undo(split) == 200
    assert people(db, second)[0] == monica
    db.expire_all()
    assert db.get(Author, other) is None
    # Bob sees none of it: he has no paper of theirs.
    assert bob.get(f"/api/authors/{monica}").status_code == 404

    # Kept apart: suggested again once undone.
    ada.post(f"/api/authors/{monica}/apart", {"other_id": str(back)})
    assert authors.are_apart(db, monica, back)
    apart = changes(monica)[0]
    assert apart["kind"] == "apart" and undo(apart) == 200
    assert not authors.are_apart(db, monica, back)
    assert ada.post(f"/api/author-changes/{uuid.uuid4()}/undo").status_code == 404


def test_what_cannot_be_undone(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    full = paper(ada, "Full", "Benito, Mónica")
    short = paper(ada, "Short", "Benito, M.")
    authors.link_waiting(db)
    [monica] = people(db, full)
    [m] = people(db, short)
    keep, other = db.get(Author, monica), db.get(Author, m)
    assert keep is not None and other is not None
    authors.merge(db, keep, other)
    merged = db.scalars(select(AuthorChange)).one()
    assert merged.user_id is None
    # Its paper went to someone else since.
    authorship = db.get(Authorship, (uuid.UUID(short), 1))
    assert authorship is not None
    authors.assign(db, authorship, None)
    with pytest.raises(authors.Refused, match="none of those papers"):
        authors.undo(db, merged)
    db.rollback()
    # A split whose new person is gone; a change whose person is gone.
    new = authors.split(db, keep, [uuid.UUID(full)])
    split = db.scalars(select(AuthorChange).where(AuthorChange.kind == "split")).one()
    db.delete(new)
    db.commit()
    with pytest.raises(authors.Refused, match="other person"):
        authors.undo(db, split)
    db.rollback()
    db.delete(keep)
    db.commit()
    with pytest.raises(authors.Refused, match="no longer there"):
        authors.undo(db, split)


def test_others_namesakes_stay_theirs(client: TestClient, db: Session) -> None:
    """A namesake known only from someone else's papers is no candidate, and
    a fix by them names no one one cannot see."""
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    physics = paper(ada, "Physics", "Benito, Mónica")
    biology = paper(ada, "Biology", "Benito, Mónica")
    short = paper(ada, "Short", "Benito, M. R.")
    authors.link_waiting(db)
    [monica] = people(db, physics)
    [m] = people(db, short)
    assert monica is not None and m is not None
    ada.post(f"/api/authors/{monica}/split", {"item_ids": [biology]})
    alone = paper(bob, "Bob's", "Benito, Mónica")
    authors.link_waiting(db)
    assert people(db, alone) == [None]
    [check] = bob.get("/api/authors-to-check").json()
    assert check["candidates"] == []  # both Mónicas are Ada's alone
    # Jane Smith is on papers of both; "J. K. Smith" on Ada's alone.
    paper(ada, "Ada's", "Smith, Jane")
    paper(ada, "Initials", "Smith, J. K.")
    bobs = paper(bob, "Bob's too", "Smith, Jane")
    authors.link_waiting(db)
    [jane] = people(db, bobs)
    jk = db.scalar(select(Author.id).where(Author.name == "J. K. Smith"))
    ada.post(f"/api/authors/{jane}/merge", {"other_id": str(jk)})
    [merged] = bob.get(f"/api/authors/{jane}").json()["changes"]
    assert (merged["other_name"], merged["papers"], merged["by_you"]) == (
        None,
        0,
        False,
    )
    assert ada.get(f"/api/authors/{jane}").json()["changes"][0]["other_name"] == (
        "J. K. Smith"
    )
