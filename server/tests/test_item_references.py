"""Papers' reference lists (arXiv's LaTeX source, Crossref, the PDF) and the
papers citing a paper: found in the background, read on the item page and
by AI assistants."""

import gzip
import io
import tarfile
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from paperus import item_references, jobs
from paperus.config import Settings
from paperus.db import make_sessionmaker
from paperus.importing.references import Pacer
from paperus.item_references import (
    Pacers,
    SourceUnavailable,
    short_authors,
    split_references,
)
from paperus.jobs import WorkerContext, tasks
from paperus.models import Collection, File, Import, Item, ItemReference, User
from paperus.processing import process_file
from paperus.storage import BlobStore
from paperus.system import load_config, save_config
from tests.conftest import FakeDOIRegistry, FakeML
from tests.pdfs import make_pdf
from tests.people import Person
from tests.test_mcp import Assistant, token

NO_PAUSE = Pacers(Pacer(0), Pacer(0))

LOVELACE_DOI = "10.1103/physrevlett.1.1"
BBL = r"""
\begin{thebibliography}{3}
\bibitem{lovelace} A. Lovelace, Notes on the analytical engine,
  \doi{10.1103/PhysRevLett.1.1}.
\bibitem{babbage} C. Babbage, The difference engine, arXiv:2401.00002 (2024).
\bibitem{menabrea} L. F. Menabrea, Sketch of the analytical engine,
  Biblioth\`eque Universelle de Gen\`eve 82 (1842).
\end{thebibliography}
"""
REFERENCE_PAGE = [
    "References",
    "[1] A. Lovelace, Notes on the analytical engine, Phys. Rev. Lett. 1, 1",
    "(1843), doi:10.1103/PhysRevLett.1.1",
    "[2] C. Babbage, The difference engine, arXiv:2401.00002 (2024).",
    "[3] L. F. Menabrea, Sketch of the analytical engine, Geneva 82 (1842).",
]
MENABREA = {
    "DOI": "10.5555/menabrea",
    "title": ["Sketch of the analytical engine"],
    "author": [{"family": "Menabrea"}],
    "issued": {"date-parts": [[1842]]},
    "container-title": ["Bibliothèque Universelle de Genève"],
    "score": 90.0,
}


def tar_gz(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class FakeSources:
    """doi.org, arXiv's e-prints and Crossref (works and search)."""

    def __init__(self, registry: FakeDOIRegistry) -> None:
        self.registry = registry
        self.e_prints: dict[str, bytes] = {}
        self.e_print_status: int | None = None
        self.works: dict[str, Any] = {}
        """DOI → the reference list Crossref has (or a whole answer)."""
        self.works_status: int | None = None
        self.matches: dict[str, dict[str, Any]] = {}
        self.openalex: dict[str, dict[str, Any]] = {}
        """DOI (lower case) → the work OpenAlex has."""
        self.openalex_status: int | None = None
        self.down = False
        self.asked: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("down", request=request)
        host, path = request.url.host, request.url.path
        self.asked.append(host + path)
        if host == "doi.org":
            return self.registry(request)
        if host == "arxiv.org" and path.startswith("/e-print/"):
            if self.e_print_status:
                return httpx2.Response(self.e_print_status)
            paper = path.removeprefix("/e-print/")
            if paper not in self.e_prints:
                return httpx2.Response(404)
            return httpx2.Response(200, content=self.e_prints[paper])
        if host == "api.openalex.org" and path == "/works":
            if self.openalex_status:
                return httpx2.Response(self.openalex_status)
            dois = request.url.params["filter"].removeprefix("doi:").split("|")
            found = [
                {"doi": f"https://doi.org/{doi}", **self.openalex[doi]}
                for doi in dois
                if doi in self.openalex
            ]
            return httpx2.Response(200, json={"results": found})
        if host == "api.crossref.org" and path == "/works":
            text = request.url.params["query.bibliographic"]
            items = [m for key, m in self.matches.items() if key in text]
            return httpx2.Response(200, json={"message": {"items": items[:1]}})
        if host == "api.crossref.org":
            if self.works_status:
                return httpx2.Response(self.works_status)
            doi = path.removeprefix("/works/")
            if doi not in self.works:
                return httpx2.Response(404)
            answer = self.works[doi]
            if isinstance(answer, list):
                answer = {"message": {"DOI": doi, "reference": answer}}
            return httpx2.Response(200, json=answer)
        return httpx2.Response(404)


@pytest.fixture
def sources(doi_registry: FakeDOIRegistry) -> FakeSources:
    return FakeSources(doi_registry)


@pytest.fixture
def http(sources: FakeSources) -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(sources))


@pytest.fixture
def job_app(monkeypatch: pytest.MonkeyPatch) -> App:
    """Jobs in memory, runnable by their queued names (as in test_worker)."""
    app = App(connector=InMemoryConnector())
    for task in set(tasks.tasks.values()):
        name = f"paperus:{task.name.rsplit(':', 1)[-1]}"
        monkeypatch.setattr(task, "name", name)
        monkeypatch.setattr(task, "blueprint", app)
        app.tasks[name] = task
    return app


@pytest.fixture
def worker(
    client: TestClient,
    engine: Engine,
    settings: Settings,
    blobs: BlobStore,
    fake_ml: FakeML,
    http: httpx2.Client,
    job_app: App,
    monkeypatch: pytest.MonkeyPatch,
) -> App:
    """The worker's context (its web is the fake sources; no pauses), and
    the website's too."""
    context = WorkerContext(
        engine=engine,
        sessions=make_sessionmaker(engine),
        blobs=blobs,
        http=http,
        ml=fake_ml.client(),
        settings=settings,
    )
    monkeypatch.setattr(jobs, "_context", context)
    monkeypatch.setattr(item_references, "PACERS", NO_PAUSE)
    client.app.state.http = http  # ty: ignore[unresolved-attribute]
    return job_app


def run_jobs(app: App) -> dict[str, int]:
    app.run_worker(wait=False, install_signal_handlers=False, listen_notify=False)
    assert isinstance(app.connector, InMemoryConnector)
    ran: dict[str, int] = {}
    for job in app.connector.jobs.values():
        key = f"{job['task_name'].removeprefix('paperus:')} {job['status']}"
        ran[key] = ran.get(key, 0) + 1
    app.connector.jobs.clear()
    return ran


def paper(
    person: Person, title: str, library: str | None = None, **ids: str
) -> dict[str, Any]:
    """A paper with these identifiers (scheme=value), details typed in."""
    response = person.post(
        "/api/items",
        json={
            "metadata": {"title": title, "type": "article-journal"},
            "identifiers": [{"scheme": s, "value": v} for s, v in ids.items()],
            "library_id": library,
        },
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def attach_pdf(
    person: Person, db: Session, blobs: BlobStore, item: dict[str, Any], pdf: bytes
) -> uuid.UUID:
    file = person.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("paper.pdf", pdf, "application/pdf")},
    ).json()
    process_file(db, blobs, uuid.UUID(file["id"]))
    return uuid.UUID(file["id"])


def item_of(db: Session, item: dict[str, Any]) -> Item:
    db.expire_all()
    found = db.get(Item, uuid.UUID(item["id"]))
    assert found is not None
    return found


def check(db: Session, http: httpx2.Client, item: dict[str, Any]) -> int | None:
    return item_references.check(db, http, item_of(db, item), pacers=NO_PAUSE)


# --- splitting a PDF's reference list ------------------------------------------


def test_numbered_lists_are_split() -> None:
    bracketed = (
        "References [1] A. Einstein, B. Podolsky and N. Rosen, Can quantum-"
        "mechanical description be complete? Phys. Rev. 47, 777 (1935). "
        "[2] J. S. Bell, On the Einstein Podolsky Rosen paradox, Physics 1, 195 "
        "(1964). [3] S. J. Freedman and J. F. Clauser, Experimental test, Phys. "
        "Rev. Lett. 28, 938 (1972). " + "Appendix text " * 200
    )
    pieces = split_references(bracketed)
    assert [p[:12] for p in pieces] == ["A. Einstein,", "J. S. Bell, ", "S. J. Freedm"]
    # The last one runs to the end of the section: cut.
    assert len(pieces[-1]) < 600 and pieces[-1].endswith("…")

    dotted = (
        "Phys. Rev. B 15, 11475 (1995) 1. M. Cassidy et al., presented at the "
        "Workshop on floating charges, 2024. 2. Smith, J. A study of 12 things. "
        "Nature 5, 1-12. (2020). 3. Jones K., Another thing about stuff, Science "
        "3, 44 (2019). 4. Brown, L. Final one, J. Chem. 4, 5 (2001)."
    )
    assert [p[:8] for p in split_references(dotted)] == [
        "M. Cassi",
        "Smith, J",
        "Jones K.",
        "Brown, L",
    ]
    # AIP: the number before the initials.
    glued = (
        "REFERENCES 1S. Probst, F. B. Song and M. Weides, Efficient analysis of "
        "scattering data, Rev. Sci. Instrum. 86, 024706 (2015). 2E. Kawakami, J. "
        "Chen and D. Konstantinov, Blueprint for quantum computing, Phys. Rev. "
        "Appl. 20, 054022 (2023). 3K. D. Petersson and J. R. Petta, Circuit "
        "quantum electrodynamics with a spin qubit, Nature 490, 380 (2012)."
    )
    assert [p[:10] for p in split_references(glued)] == [
        "S. Probst,",
        "E. Kawakam",
        "K. D. Pete",
    ]


def test_author_year_lists_are_split() -> None:
    text = (
        "References Morgado, B. E., Sicardy, B., Braga-Ribas, F., et al. 2023, "
        "Nature, 614, 239, doi: 10.1038/s41586-022-05629-6 Murray, C. D., & "
        "Dermott, S. F. 1999, Solar System Dynamics, doi: 10.1017/CBO9781139174817 "
        "Abanin, D., W. De Roeck, and F. Huveneers, 2016, Ann. Phys. 372, 1. "
        "Smith, J. (2020). A title about things. Journal of Stuff, 12(3), 45-67. "
        "van der Berg, A. (2019). In: Jones, K. (Ed.), Book. Publisher. Leftover, "
        "A. without any year"
    )
    pieces = split_references(text)
    assert [p.split(",")[0] for p in pieces] == [
        "Morgado",
        "Murray",
        "Abanin",
        "Smith",
        "van der Berg",
    ]
    # A piece without a year belongs to the one before.
    assert pieces[-1].endswith("Leftover, A. without any year")


def test_what_cannot_be_split() -> None:
    assert split_references("") == []
    assert split_references("References Just one paragraph of prose.") == []
    # Too short to be references.
    assert split_references("[1] a [2] b [3] c [4] d") == []
    assert short_authors([]) is None
    assert short_authors(["Smith"]) == "Smith"
    assert short_authors(["Smith", "Jones"]) == "Smith and Jones"
    assert short_authors(["Smith", "Jones", "Brown"]) == "Smith et al."


# --- the sources ------------------------------------------------------------------


def test_from_arxiv_sources(
    client: TestClient, db: Session, sources: FakeSources, http: httpx2.Client
) -> None:
    ada = Person(client, db, "ada")
    preprint = paper(ada, "Engines", arxiv="2611.00001")
    sources.e_prints["2611.00001"] = tar_gz({"main.bbl": BBL.encode()})
    assert check(db, http, preprint) == 3
    item = item_of(db, preprint)
    assert item.references_source == "arxiv"
    assert item.references_checked_at is not None
    rows = db.scalars(
        select(ItemReference)
        .where(ItemReference.item_id == item.id)
        .order_by(ItemReference.position)
    ).all()
    assert [(r.position, r.doi, r.arxiv) for r in rows] == [
        (1, LOVELACE_DOI, None),
        (2, None, "2401.00002"),
        (3, None, None),
    ]
    assert rows[2].text.startswith("L. F. Menabrea, Sketch of the analytical engine")
    assert "Bibliothèque" in rows[2].text

    # A single gzipped .tex with its thebibliography.
    sources.e_prints["2611.00001"] = gzip.compress(
        (r"\documentclass{article}\begin{document}" + BBL + r"\end{document}").encode()
    )
    assert check(db, http, preprint) == 3

    # A .bib: the entries the paper cites, as a reference prints them.
    tex = (
        r"\documentclass{article}\begin{document}\cite{a,c}"
        r"\bibliography{refs}\end{document}"
    )
    bib = (
        "@article{a, author={Lovelace, Ada and Babbage, Charles and Somerville, "
        "Mary}, title={Notes}, journal={Taylor's Memoirs}, volume={3}, "
        "year={1843}, doi={10.1103/PhysRevLett.1.1}}\n"
        "@article{b, title={Not cited}}\n"
        "@misc{c, author={Menabrea, Luigi}, year={1842}}\n"
    )
    sources.e_prints["2611.00001"] = tar_gz(
        {"main.tex": tex.encode(), "refs.bib": bib.encode()}
    )
    assert check(db, http, preprint) == 2
    first, second = db.scalars(
        select(ItemReference)
        .where(ItemReference.item_id == item.id)
        .order_by(ItemReference.position)
    ).all()
    assert (first.title, first.authors, first.year, first.container) == (
        "Notes",
        "Lovelace et al.",
        1843,
        "Taylor's Memoirs",
    )
    assert (
        first.text == "Lovelace, Babbage, Somerville. Notes. Taylor's Memoirs. 3. 1843"
    )
    assert (second.title, second.text) == (None, "Menabrea. 1842")


def test_arxiv_without_a_list(
    client: TestClient,
    db: Session,
    sources: FakeSources,
    http: httpx2.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ada = Person(client, db, "ada")
    preprint = paper(ada, "Engines", arxiv="2611.00001")
    # Not at arXiv, only a PDF, no LaTeX, a BibTeX file, too large: no list.
    for answer in (None, b"%PDF-1.5 a paper", b"hello", b"@article{a, title={A}}"):
        sources.e_prints.pop("2611.00001", None)
        if answer is not None:
            sources.e_prints["2611.00001"] = answer
        assert check(db, http, preprint) == 0
    sources.e_prints["2611.00001"] = tar_gz({"main.bbl": BBL.encode()})
    monkeypatch.setattr(item_references, "MAX_E_PRINT_BYTES", 10)
    assert check(db, http, preprint) == 0
    assert item_of(db, preprint).references_source is None

    # arXiv not answering: looked at again later.
    db.execute(update(Item).values(references_checked_at=None))
    db.commit()
    sources.e_print_status = 503
    assert check(db, http, preprint) is None
    sources.e_print_status = None
    sources.down = True
    assert check(db, http, preprint) is None
    assert item_of(db, preprint).references_checked_at is None
    with pytest.raises(SourceUnavailable):
        item_references.from_arxiv(http, "2611.00001", NO_PAUSE)


def test_from_crossref(
    client: TestClient, db: Session, sources: FakeSources, http: httpx2.Client
) -> None:
    ada = Person(client, db, "ada")
    journal = paper(ada, "Engines", doi="10.1000/engines")
    sources.works["10.1000/engines"] = [
        {"key": "r1", "DOI": "10.1103/PhysRevLett.1.1", "unstructured": "Lovelace"},
        {
            "key": "r2",
            "unstructured": "C. Babbage, <i>The difference engine</i>, "
            "arXiv:2401.00002 &amp; more",
        },
        {
            "key": "r3",
            "author": "Menabrea",
            "article-title": "Sketch of the analytical engine",
            "journal-title": "Bibl. Univ.",
            "volume": "82",
            "first-page": "1",
            "year": "1842",
        },
        {"key": "r4", "DOI": "10.1000/only-a-doi"},
        {"key": "r5", "year": "0012"},
        "not a reference",
    ]
    assert check(db, http, journal) == 4
    item = item_of(db, journal)
    assert item.references_source == "crossref"
    rows = db.scalars(
        select(ItemReference)
        .where(ItemReference.item_id == item.id)
        .order_by(ItemReference.position)
    ).all()
    assert [(r.doi, r.arxiv) for r in rows] == [
        (LOVELACE_DOI, None),
        (None, "2401.00002"),
        (None, None),
        ("10.1000/only-a-doi", None),
    ]
    assert rows[1].text == "C. Babbage, The difference engine, arXiv:2401.00002 & more"
    assert rows[2].text == (
        "Menabrea, Sketch of the analytical engine, Bibl. Univ., 82, 1, (1842)"
    )
    assert (rows[2].authors, rows[2].year, rows[2].container) == (
        "Menabrea",
        1842,
        "Bibl. Univ.",
    )
    assert rows[3].text == "doi:10.1000/only-a-doi"
    # The contact email goes along, as Crossref asks.
    sources.asked.clear()
    item_references.from_crossref(http, "10.1000/engines", NO_PAUSE, "a@b.org")
    assert sources.asked == ["api.crossref.org/works/10.1000/engines"]

    # Without references, unknown or garbled: none; not answering: later.
    sources.works["10.1000/engines"] = []
    assert item_references.from_crossref(http, "10.1000/engines", NO_PAUSE) == []
    assert item_references.from_crossref(http, "10.1000/unknown", NO_PAUSE) == []
    sources.works["10.1000/engines"] = {"message": "garbled"}
    assert item_references.from_crossref(http, "10.1000/engines", NO_PAUSE) == []
    sources.works_status = 500
    with pytest.raises(SourceUnavailable):
        item_references.from_crossref(http, "10.1000/engines", NO_PAUSE)
    sources.down = True
    with pytest.raises(SourceUnavailable):
        item_references.from_crossref(http, "10.1000/engines", NO_PAUSE)


def test_a_journals_paper_asks_crossref_first(
    client: TestClient, db: Session, sources: FakeSources, http: httpx2.Client
) -> None:
    """Published and on arXiv: Crossref's list, without arXiv's 3 s pause or
    download; arXiv's source only if Crossref has none, and not where
    arXiv may not be asked (the job then goes on in arXiv's queue)."""
    ada = Person(client, db, "ada")
    both = paper(ada, "Engines", doi="10.1000/engines", arxiv="2611.00001")
    sources.e_prints["2611.00001"] = tar_gz({"main.bbl": BBL.encode()})
    sources.works["10.1000/engines"] = [{"key": "r1", "DOI": LOVELACE_DOI}]
    sources.asked.clear()
    assert check(db, http, both) == 1
    assert item_of(db, both).references_source == "crossref"
    assert not [url for url in sources.asked if "arxiv" in url]

    sources.works["10.1000/engines"] = []
    with pytest.raises(item_references.NeedsArxiv):
        item_references.check(db, http, item_of(db, both), pacers=NO_PAUSE, arxiv=False)
    assert check(db, http, both) == 3
    assert item_of(db, both).references_source == "arxiv"
    # A preprint alone: arXiv straight away (its own DOI is DataCite's).
    preprint = paper(ada, "Sketch", doi="10.48550/arXiv.2611.00002", arxiv="2611.00002")
    sources.asked.clear()
    with pytest.raises(item_references.NeedsArxiv):
        item_references.check(
            db, http, item_of(db, preprint), pacers=NO_PAUSE, arxiv=False
        )
    assert sources.asked == []


def test_from_the_pdf(
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    sources: FakeSources,
    http: httpx2.Client,
) -> None:
    ada = Person(client, db, "ada")
    # Crossref has no references for it: the PDF's own list.
    journal = paper(ada, "Engines", doi="10.1000/engines")
    sources.works["10.1000/engines"] = []
    pdf = make_pdf(
        [
            ["Engines", "On computing machines."],
            [
                *REFERENCE_PAGE,
                "Downloaded from https://example.org/doi/10.1000/engines by Ada",
                "[4] Lovelace, A. Our own paper, doi:10.1000/engines (1843).",
            ],
        ]
    )
    attach_pdf(ada, db, blobs, journal, pdf)
    assert check(db, http, journal) == 4
    item = item_of(db, journal)
    assert item.references_source == "pdf"
    rows = db.scalars(
        select(ItemReference)
        .where(ItemReference.item_id == item.id)
        .order_by(ItemReference.position)
    ).all()
    assert [(r.doi, r.arxiv, r.year) for r in rows] == [
        (LOVELACE_DOI, None, 1843),
        (None, "2401.00002", 2024),
        (None, None, 1842),
        # The paper's own DOI (as in a download note) is no reference.
        (None, None, 1843),
    ]
    assert rows[0].text.startswith("A. Lovelace, Notes on the analytical engine")

    # Without a reference section, or without read text: no list.
    other = paper(ada, "Prose")
    attach_pdf(ada, db, blobs, other, make_pdf([["Only prose here, no list."]]))
    unread = ada.post(
        f"/api/items/{other['id']}/files",
        files={"upload": ("later.pdf", pdf, "application/pdf")},
    )
    assert unread.status_code == 201
    assert check(db, http, other) == 0


def test_a_list_found_stays(
    client: TestClient, db: Session, sources: FakeSources, http: httpx2.Client
) -> None:
    ada = Person(client, db, "ada")
    preprint = paper(ada, "Engines", arxiv="2611.00001")
    sources.e_prints["2611.00001"] = tar_gz({"main.bbl": BBL.encode()})
    assert check(db, http, preprint) == 3
    change = item_of(db, preprint).change
    # Looking again finds nothing now: the list stays.
    del sources.e_prints["2611.00001"]
    assert check(db, http, preprint) == 0
    item = item_of(db, preprint)
    assert item.references_source == "arxiv"
    assert (
        len(ada.get(f"/api/items/{preprint['id']}/references").json()["references"])
        == 3
    )
    # Looking is no change of the paper (sync clients see none).
    assert item.change == change


def test_which_papers_wait(
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    sources: FakeSources,
    http: httpx2.Client,
) -> None:
    ada = Person(client, db, "ada")
    first = paper(ada, "First")
    second = paper(ada, "Second")
    trashed = paper(ada, "Trashed")
    ada.delete(f"/api/items/{trashed['id']}")
    waiting = [str(i.id) for i in item_references.waiting(db)]
    assert waiting == [first["id"], second["id"]]
    for item in item_references.waiting(db):
        assert item_references.check(db, http, item, pacers=NO_PAUSE) == 0
    assert item_references.waiting(db) == []
    # A paper without list gets a file: looked at again.
    attach_pdf(ada, db, blobs, first, make_pdf([REFERENCE_PAGE]))
    [again] = item_references.waiting(db)
    assert str(again.id) == first["id"]
    assert item_references.check(db, http, again, pacers=NO_PAUSE) == 3
    assert item_references.waiting(db) == []


# --- on the website ---------------------------------------------------------------


@pytest.fixture
def library(
    client: TestClient, db: Session, sources: FakeSources, http: httpx2.Client
) -> dict[str, Any]:
    """Ada's preprint with its list; Lovelace's paper in her library, a
    trashed copy of Babbage's and Bob's private one."""
    ada = Person(client, db, "ada")
    bob = Person(client, db, "bob")
    preprint = paper(ada, "Engines", arxiv="2611.00001", doi="10.1000/engines")
    lovelace = paper(ada, "Notes on the analytical engine", doi=LOVELACE_DOI)
    babbage = paper(ada, "The difference engine", arxiv="2401.00002")
    ada.delete(f"/api/items/{babbage['id']}")
    paper(bob, "The difference engine", arxiv="2401.00002")
    sources.e_prints["2611.00001"] = tar_gz({"main.bbl": BBL.encode()})
    check(db, http, preprint)
    client.app.state.http = http  # ty: ignore[unresolved-attribute]
    return {"ada": ada, "bob": bob, "preprint": preprint, "lovelace": lovelace}


def test_references_on_the_item_page(
    db: Session, library: dict[str, Any], sources: FakeSources
) -> None:
    ada, bob = library["ada"], library["bob"]
    preprint, lovelace = library["preprint"], library["lovelace"]
    found = ada.get(f"/api/items/{preprint['id']}/references").json()
    assert found["source"] == "arxiv" and found["checked_at"]
    references = found["references"]
    assert [(r["position"], r["doi"], r["arxiv"]) for r in references] == [
        (1, LOVELACE_DOI, None),
        (2, None, "2401.00002"),
        (3, None, None),
    ]
    # In Ada's library: linked; trashed or someone else's: not.
    assert references[0]["item"]["id"] == lovelace["id"]
    assert references[1]["item"] is None and references[2]["item"] is None
    # Bob cannot see the paper at all.
    assert bob.get(f"/api/items/{preprint['id']}/references").status_code == 404
    # Not looked at yet: nothing.
    fresh = paper(ada, "Fresh")
    assert ada.get(f"/api/items/{fresh['id']}/references").json() == {
        "source": None,
        "checked_at": None,
        "references": [],
    }

    # Cited by: Lovelace's paper by the preprint; not once it is archived.
    cited = ada.get(f"/api/items/{lovelace['id']}/cited-by").json()
    assert [c["id"] for c in cited] == [preprint["id"]]
    assert ada.get(f"/api/items/{fresh['id']}/cited-by").json() == []
    ada.put(f"/api/items/{preprint['id']}/archive")
    assert ada.get(f"/api/items/{lovelace['id']}/cited-by").json() == []
    # Bob's copy of Babbage's paper: cited by a paper he cannot see.
    babbage = bob.get("/api/items").json()[0]
    assert bob.get(f"/api/items/{babbage['id']}/cited-by").json() == []


def test_find_a_reference_on_crossref(
    db: Session, library: dict[str, Any], sources: FakeSources
) -> None:
    ada, bob = library["ada"], library["bob"]
    url = f"/api/items/{library['preprint']['id']}/references"
    # Not certain (Crossref's score too low): not taken.
    sources.matches = {"Menabrea": {**MENABREA, "score": 20}}
    response = ada.post(f"{url}/3/find")
    assert response.status_code == 422
    sources.matches = {"Menabrea": {**MENABREA, "DOI": "not a doi"}}
    assert ada.post(f"{url}/3/find").status_code == 422
    # Certain: its DOI, title and journal taken.
    sources.matches = {"Menabrea": MENABREA}
    found = ada.post(f"{url}/3/find").json()
    assert (found["doi"], found["title"], found["year"], found["container"]) == (
        "10.5555/menabrea",
        "Sketch of the analytical engine",
        1842,
        "Bibliothèque Universelle de Genève",
    )
    assert found["item"] is None
    # Once it has a DOI, nothing is searched; a linked one shows its paper.
    sources.asked.clear()
    assert ada.post(f"{url}/3/find").json()["doi"] == "10.5555/menabrea"
    assert ada.post(f"{url}/1/find").json()["item"]["id"] == library["lovelace"]["id"]
    assert sources.asked == []
    assert ada.post(f"{url}/9/find").status_code == 404
    assert bob.post(f"{url}/3/find").status_code == 404


def test_import_all_references(
    db: Session,
    library: dict[str, Any],
    worker: App,
    doi_registry: FakeDOIRegistry,
    sources: FakeSources,
) -> None:
    ada = library["ada"]
    preprint = library["preprint"]
    doi_registry.records["10.48550/arxiv.2401.00002"] = {
        "type": "article",
        "title": "The difference engine",
    }
    # Menabrea's found on Crossref (but unknown to doi.org): added as it is.
    sources.matches = {"Menabrea": MENABREA}
    ada.post(f"/api/items/{preprint['id']}/references/3/find")
    started = ada.post(f"/api/items/{preprint['id']}/references/import")
    assert started.status_code == 201
    record = started.json()
    assert record["filename"] == "References of Engines"
    assert record["format"] == "references"
    assert run_jobs(worker) == {"import_references succeeded": 1}
    done = ada.get(f"/api/imports/{record['id']}").json()
    assert done["status"] == "done", done
    assert (done["report"]["added"], done["report"]["found"]) == (1, 2)
    # Lovelace's paper found; Babbage's restored from the trash.
    [collection] = db.scalars(select(Collection)).all()
    assert collection.name == "References of Engines"
    titles = sorted(ada.titles(collection=str(collection.id)))
    assert titles == [
        "Notes on the analytical engine",
        "Sketch of the analytical engine",
        "The difference engine",
    ]
    added = ada.get(f"/api/items?collection={collection.id}&title=Sketch").json()
    assert (added[0]["year"], added[0]["container_title"]) == (
        1842,
        "Bibliothèque Universelle de Genève",
    )

    # Text-only references are left out.
    text_only = ItemReference(item_id=uuid.uuid4(), position=1, text="Private talk")
    assert item_references.to_import([text_only]) == []

    # The paper gone meanwhile: the import fails, saying so.
    again = ada.post(f"/api/items/{preprint['id']}/references/import").json()
    ada.delete(f"/api/items/{preprint['id']}")
    assert run_jobs(worker) == {"import_references succeeded": 1}
    failed = ada.get(f"/api/imports/{again['id']}").json()
    assert (failed["status"], failed["error"]) == (
        "failed",
        "The paper is no longer there.",
    )
    assert ada.post(f"/api/items/{preprint['id']}/references/import").status_code == 409


def test_import_all_for_someone_gone(
    db: Session, library: dict[str, Any], worker: App
) -> None:
    ada = library["ada"]
    record = ada.post(f"/api/items/{library['preprint']['id']}/references/import")
    db.execute(
        update(User)
        .where(User.username == "ada")
        .values(deactivated_at=datetime.now(UTC))
    )
    db.commit()
    assert run_jobs(worker) == {"import_references succeeded": 1}
    db.expire_all()
    row = db.get(Import, uuid.UUID(record.json()["id"]))
    assert row is not None
    assert (row.status, row.error) == (
        "failed",
        "The person who started the import cannot log in.",
    )
    # Done, or gone: not run again.
    jobs.queue_reference_import(worker, row.id, row.library_id, uuid.uuid4())
    jobs.queue_reference_import(worker, uuid.uuid4(), row.library_id, uuid.uuid4())
    assert run_jobs(worker) == {"import_references succeeded": 2}


# --- in the background ----------------------------------------------------------


def configure(db: Session, settings: Settings, **changes: object) -> None:
    config = load_config(db, settings)
    for name, value in changes.items():
        setattr(config, name, value)
    save_config(db, config)
    db.commit()


def test_looked_for_after_a_file_is_read(
    client: TestClient, db: Session, worker: App, settings: Settings
) -> None:
    ada = Person(client, db, "ada")
    item = paper(ada, "Engines")
    ada.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("p.pdf", make_pdf([REFERENCE_PAGE]), "application/pdf")},
    )
    ran = run_jobs(worker)
    assert ran["extract_text succeeded"] == 1
    assert ran["find_item_references succeeded"] == 1
    found = ada.get(f"/api/items/{item['id']}/references").json()
    assert found["source"] == "pdf" and len(found["references"]) == 3

    # It has a list: another file brings no new look.
    ada.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("q.pdf", make_pdf([["Only prose."]]), "application/pdf")},
    )
    assert "find_item_references succeeded" not in run_jobs(worker)

    # Looked at, nothing found, and a file without references: no look.
    other = paper(ada, "Other")
    db.execute(update(Item).values(references_checked_at=datetime.now(UTC)))
    db.commit()
    ada.post(
        f"/api/items/{other['id']}/files",
        files={"upload": ("r.pdf", make_pdf([["Prose again."]]), "application/pdf")},
    )
    assert "find_item_references succeeded" not in run_jobs(worker)

    # Switched off: none either.
    configure(db, settings, find_references=False)
    third = paper(ada, "Third")
    ada.post(
        f"/api/items/{third['id']}/files",
        files={"upload": ("s.pdf", make_pdf([REFERENCE_PAGE]), "application/pdf")},
    )
    assert "find_item_references succeeded" not in run_jobs(worker)
    # A job queued before the switch does nothing either.
    jobs.queue_references(worker, uuid.UUID(third["id"]))
    assert run_jobs(worker) == {"find_item_references succeeded": 1}
    assert ada.get(f"/api/items/{third['id']}/references").json()["source"] is None
    # Asked for by someone: looked for all the same.
    assert ada.post(f"/api/items/{third['id']}/references/refresh").status_code == 202
    assert run_jobs(worker) == {"find_item_references succeeded": 1}
    assert ada.get(f"/api/items/{third['id']}/references").json()["source"] == "pdf"
    # A paper gone meanwhile: nothing to do.
    jobs.queue_references(worker, uuid.uuid4(), again=True)
    assert run_jobs(worker) == {"find_item_references succeeded": 1}


def test_the_hourly_job(
    client: TestClient,
    db: Session,
    worker: App,
    settings: Settings,
    sources: FakeSources,
) -> None:
    ada = Person(client, db, "ada")
    admin = Person(client, db, "root", admin=True)
    preprint = paper(ada, "Engines", arxiv="2611.00001")
    sources.e_prints["2611.00001"] = tar_gz({"main.bbl": BBL.encode()})
    configure(db, settings, find_references=False)
    assert admin.post("/api/admin/jobs/references").status_code == 202
    assert run_jobs(worker) == {"find_reference_lists succeeded": 1}
    assert item_of(db, preprint).references_checked_at is None
    configure(db, settings, find_references=True)
    jobs.queue_reference_lists(worker)
    jobs.queue_reference_lists(worker)  # once is enough
    # Each paper's own lookup, at Crossref's queue first: a preprint goes on
    # in arXiv's (one job there, the list from its LaTeX source).
    assert run_jobs(worker) == {
        "find_reference_lists succeeded": 1,
        "find_item_references succeeded": 2,
    }
    assert item_of(db, preprint).references_source == "arxiv"
    # Readers of the paper may ask too; others not; not in the trash.
    bob = Person(client, db, "bob")
    url = f"/api/items/{preprint['id']}/references/refresh"
    assert bob.post(url).status_code == 404
    ada.delete(f"/api/items/{preprint['id']}")
    assert ada.post(url).status_code == 409


# --- AI assistants --------------------------------------------------------------


def test_mcp_tools(client: TestClient, db: Session, library: dict[str, Any]) -> None:
    ada = library["ada"]
    assistant = Assistant(client, token(ada, "papers.read"))
    found = assistant.call("get_references", paper_id=library["preprint"]["id"])
    assert found["source"] == "arxiv"
    kinds = [(r["position"], r["kind"]) for r in found["references"]]
    assert kinds == [(1, "paper"), (2, "link"), (3, "text")]
    first = found["references"][0]
    assert first["paper_id"] == library["lovelace"]["id"]
    assert first["title"] == "Notes on the analytical engine"
    assert first["link"].endswith(f"/items/{library['lovelace']['id']}")
    citing = assistant.call("cited_by", paper_id=library["lovelace"]["id"])
    assert [c["paper_id"] for c in citing] == [library["preprint"]["id"]]
    fresh = paper(ada, "Fresh")
    assert assistant.call("get_references", paper_id=fresh["id"]) == {"references": []}


def test_files_of_other_versions_and_trashed_files(
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    http: httpx2.Client,
    sources: FakeSources,
) -> None:
    ada = Person(client, db, "ada")
    item = paper(ada, "Engines")
    file_id = attach_pdf(ada, db, blobs, item, make_pdf([REFERENCE_PAGE]))
    db.execute(
        update(File).where(File.id == file_id).values(deleted_at=datetime.now(UTC))
    )
    db.commit()
    assert check(db, http, item) == 0
    # Another version's file is read when the preferred one has none.
    version = ada.post(
        f"/api/items/{item['id']}/versions",
        json={"metadata": {"title": "Engines"}, "kind": "published"},
    )
    assert version.status_code == 201
    db.execute(update(File).where(File.id == file_id).values(deleted_at=None))
    db.commit()
    assert check(db, http, item) == 3


def test_settings_default(db: Session, settings: Settings) -> None:
    assert load_config(db, settings).find_references is True


def test_bare_dois_get_their_details(
    client: TestClient, db: Session, sources: FakeSources, http: httpx2.Client
) -> None:
    """Some publishers deposit only DOIs at Crossref: OpenAlex tells what
    they are (50 to a request); without its answer they stay bare."""
    ada = Person(client, db, "ada")
    journal = paper(ada, "Engines", doi="10.1000/engines")
    sources.works["10.1000/engines"] = [
        {"key": f"r{n}", "DOI": f"10.1000/ref{n}"} for n in range(60)
    ] + [{"key": "arxiv", "DOI": "10.48550/arXiv.2401.00002"}]
    sources.openalex = {
        f"10.1000/ref{n}": {
            "title": f"Engine number {n}",
            "publication_year": 1840 + n % 10,
            "authorships": [
                {"author": {"display_name": "Ada Lovelace"}},
                {"author": {"display_name": "Charles Babbage"}},
            ],
            "primary_location": {"source": {"display_name": "Bibl. Univ."}},
        }
        for n in range(59)
    }
    sources.openalex["10.48550/arxiv.2401.00002"] = {"title": "A preprint"}
    assert check(db, http, journal) == 61
    rows = db.scalars(
        select(ItemReference)
        .where(ItemReference.item_id == item_of(db, journal).id)
        .order_by(ItemReference.position)
    ).all()
    assert (rows[0].title, rows[0].authors, rows[0].year, rows[0].container) == (
        "Engine number 0",
        "Lovelace and Babbage",
        1840,
        "Bibl. Univ.",
    )
    assert rows[59].title is None  # OpenAlex does not know it
    assert (rows[60].title, rows[60].year, rows[60].authors) == (
        "A preprint",
        None,
        None,
    )
    assert [a for a in sources.asked if "openalex" in a] == [
        "api.openalex.org/works"
    ] * 2

    # OpenAlex not answering: the list is kept, bare.
    sources.openalex_status = 503
    found = [item_references.Found(text="x", doi="10.1000/ref1")]
    item_references.fill_details(http, found, contact_email="a@b.org", pacers=NO_PAUSE)
    assert found[0].title is None
