"""Corrections to papers, found at Crossref (``paperus.errata``)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from sqlalchemy.orm import Session

from paperus import citations, errata, jobs
from paperus.config import Settings
from paperus.importing.references import Pacer
from paperus.item_references import Pacers
from paperus.models import Item
from tests.conftest import FakeDOIRegistry
from tests.people import Person
from tests.test_worker import (
    configure,
    defer,
    job_app,  # noqa: F401 (fixture)
    run_jobs,
    web,  # noqa: F401 (fixture)
    worker,  # noqa: F401 (fixture)
)

ORIGINAL = "10.1016/j.biomaterials.2018.04.042"
APS_PAPER = "10.1103/PhysRevA.108.063502"


def correction(
    doi: str, of: str, kind: str = "erratum", **record: object
) -> dict[str, Any]:
    return {
        "DOI": doi,
        "title": [f"Corrigendum to {of}"],
        "update-to": [{"DOI": of, "type": kind}],
        **record,
    }


class Crossref:
    """Crossref's works search: corrections by what they update, and APS's
    by words of their title."""

    def __init__(self, registry: FakeDOIRegistry | None = None) -> None:
        self.registry = registry or FakeDOIRegistry()
        self.updates: dict[str, list[dict[str, Any]]] = {}
        self.found: list[dict[str, Any]] = []
        self.down = False
        self.asked: list[dict[str, str]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "doi.org":
            return self.registry(request)
        if self.down:
            return httpx2.Response(503)
        params = dict(request.url.params)
        self.asked.append(params)
        if params.get("filter", "").startswith("updates:"):
            works = self.updates.get(params["filter"].removeprefix("updates:"), [])
        else:
            works = self.found
        return httpx2.Response(200, json={"message": {"items": works}})


def paper(person: Person, title: str, doi: str, **csl: object) -> str:
    made = person.post(
        "/api/items",
        json={
            "metadata": {"title": title, "type": "article-journal", **csl},
            "identifiers": [{"scheme": "doi", "value": doi}],
        },
    )
    assert made.status_code == 201, made.text
    item_id: str = made.json()["id"]
    return item_id


def test_corrections_found_and_kept_as_links(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(errata.item_references, "PACERS", Pacers(Pacer(0), Pacer(0)))
    ada = Person(client, db, "ada")
    item_id = paper(
        ada, "Bidirectional signaling", ORIGINAL, issued={"date-parts": [[2018]]}
    )
    paper(ada, "A preprint", "10.48550/arXiv.2401.00001")
    crossref = Crossref()
    crossref.registry.records["10.1016/j.biomaterials.2024.122752"] = {
        "type": "article-journal",
        "title": "Corrigendum to Bidirectional signaling",
        "container-title": "Biomaterials",
        "volume": "312",
        "page": "122752",
        "issued": {"date-parts": [[2025, 1]]},
        "DOI": "10.1016/j.biomaterials.2024.122752",
    }
    crossref.updates[ORIGINAL] = [
        correction(
            "10.1016/j.biomaterials.2024.122752",
            ORIGINAL,
            **{
                "container-title": ["Biomaterials"],
                "volume": "312",
                "article-number": "122752",
                "issued": {"date-parts": [[2025, 1]]},
            },
        ),
        # A new version or a retraction is not an erratum; nor one of
        # another paper.
        correction("10.1016/x.new", ORIGINAL, kind="new_version"),
        correction("10.1016/x.other", "10.1016/j.other"),
    ]
    http = httpx2.Client(transport=httpx2.MockTransport(crossref))

    # Only papers with a journal's DOI: not arXiv's.
    waiting = errata.waiting(db)
    assert [str(i.id) for i in waiting] == [item_id]
    assert errata.check(db, http, waiting, contact_email="lab@example.org") == 1
    assert crossref.asked[0]["mailto"] == "lab@example.org"
    # A version of the paper, never the one shown or cited.
    shown = ada.get(f"/api/items/{item_id}").json()
    assert shown["title"] == "Bidirectional signaling"
    kinds = {v["kind"]: v for v in shown["versions"]}
    assert set(kinds) == {"other", "erratum"}
    assert [i["value"] for i in kinds["erratum"]["identifiers"]] == [
        "10.1016/j.biomaterials.2024.122752"
    ]
    assert shown["preferred_version_id"] == kinds["other"]["id"]
    # Cited with the paper in BibTeX.
    item = db.get(Item, item_id)
    assert item is not None
    entry = citations.bibtex([item])
    assert (
        "addendum = {Erratum: Biomaterials 312, 122752 (2025), "
        "doi:10.1016/j.biomaterials.2024.122752}" in entry
    )

    # Looked at: not again for half a year, and an old paper never again.
    assert errata.waiting(db) == []
    later = datetime.now(UTC) + timedelta(days=200)
    assert errata.waiting(db, now=later) == []
    item.issued_to = date.today()
    db.commit()
    assert [str(i.id) for i in errata.waiting(db, now=later)] == [item_id]
    # Crossref not answering: looked at again next time.
    crossref.down = True
    errata.check(db, http, errata.waiting(db, now=later), now=later)
    db.refresh(item)
    assert item.errata_checked_at is not None and item.errata_checked_at < later


def test_aps_errata_by_their_title(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """APS's do not say which paper they correct but in their title."""
    monkeypatch.setattr(errata.item_references, "PACERS", Pacers(Pacer(0), Pacer(0)))
    ada = Person(client, db, "ada")
    item_id = paper(
        ada,
        "Family of oscillatory electromagnetic pulses",
        APS_PAPER,
        volume="108",
        page="063502",
        issued={"date-parts": [[2023]]},
    )
    crossref = Crossref()
    crossref.found = [
        {  # the paper itself
            "DOI": APS_PAPER.lower(),
            "title": ["Family of oscillatory electromagnetic pulses"],
        },
        {  # another paper's
            "DOI": "10.1103/physreva.109.000001",
            "title": ["Erratum: Family of pulses [Phys. Rev. A 107, 063502 (2022)]"],
        },
        {
            "DOI": "10.1103/physreva.109.059901",
            "title": [
                "Erratum: Family of oscillatory electromagnetic pulses "
                "[Phys. Rev. A 108, 063502 (2023)]"
            ],
            "short-container-title": ["Phys. Rev. A"],
            "volume": "109",
            "article-number": "059901",
            "issued": {"date-parts": [[2024, 5]]},
        },
    ]
    http = httpx2.Client(transport=httpx2.MockTransport(crossref))
    assert errata.check(db, http, errata.waiting(db)) == 1
    [search] = [p for p in crossref.asked if "query.bibliographic" in p]
    assert search["filter"] == "prefix:10.1103,from-pub-date:2023"
    # Its details not at doi.org (here): as it is cited.
    versions = ada.get(f"/api/items/{item_id}").json()["versions"]
    [erratum] = [v for v in versions if v["kind"] == "erratum"]
    assert erratum["csl"]["title"] == "Erratum: Phys. Rev. A 109, 059901 (2024)"
    assert [i["value"] for i in erratum["identifiers"]] == [
        "10.1103/physreva.109.059901"
    ]
    # Found again: not added twice.
    item = db.get(Item, item_id)
    assert item is not None
    assert errata.add(db, http, item, "10.1103/PhysRevA.109.059901", "x") is False


def test_a_correction_without_its_journal_is_cited_by_its_title() -> None:
    assert (
        errata.cited({"DOI": "x", "title": ["Correction: Rain"]}) == "Correction: Rain"
    )
    assert errata.cited({"DOI": "x"}) == "Erratum"


def test_the_weekly_job(
    client: TestClient,
    db: Session,
    worker: App,  # noqa: F811
    settings: Settings,
) -> None:
    ada = Person(client, db, "ada")
    paper(ada, "Signals", ORIGINAL)
    configure(db, settings, find_errata=False)
    defer(worker, "find_errata", timestamp=0)
    assert run_jobs(worker) == {"find_errata succeeded": 1}
    assert len(errata.waiting(db)) == 1
    configure(db, settings, find_errata=True)
    jobs.queue_errata_check(worker)
    assert run_jobs(worker) == {"find_errata succeeded": 1}
