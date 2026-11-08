"""Papers Zotero kept as web pages, with a DOI in their address."""

import uuid

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedPaper, web_pages, zotero
from paperus.importing.run import run_import
from paperus.models import Import, Item, MetadataSource
from paperus.storage import BlobStore
from tests.conftest import FakeDOIRegistry
from tests.people import Person

APS = "https://journals.aps.org/prb/pdf/10.1103/PhysRevB.104.035302"
DOI = "10.1103/physrevb.104.035302"


@pytest.mark.parametrize(
    ("url", "doi"),
    [
        (APS, DOI),
        (
            "https://journals.aps.org/prb/abstract/10.1103/cxvd-mp2h",
            "10.1103/cxvd-mp2h",
        ),
        ("https://onlinelibrary.wiley.com/doi/full/10.1002/ab.2019", "10.1002/ab.2019"),
        ("https://doi.org/10.1038%2Fs41566-018-0153-0", "10.1038/s41566-018-0153-0"),
        ("https://link.springer.com/content/pdf/10.1007/s107-1.pdf", "10.1007/s107-1"),
        ("https://pubs.acs.org/doi/10.1021/acs.nl.1c01?ref=pdf", "10.1021/acs.nl.1c01"),
        # Not in the path; no DOI at all.
        ("https://www.google.com/search?q=10.1103/PhysRevB.1.1", None),
        ("https://ieeexplore.ieee.org/document/10242110", None),
        (None, None),
    ],
)
def test_doi_in_address(url: str | None, doi: str | None) -> None:
    assert web_pages.doi_in_address(url) == doi


def page(url: str, kind: str = "webpage") -> ExportedPaper:
    return ExportedPaper(csl={"type": kind, "title": url, "URL": url})


def test_web_pages_become_papers(doi_registry: FakeDOIRegistry) -> None:
    http = httpx2.Client(transport=httpx2.MockTransport(doi_registry))
    doi_registry.records[DOI] = {
        "type": "journal-article",
        "title": "Hole spin qubits",
        "container-title": "Physical Review B",
    }
    export = Export(
        format="zotero-rdf",
        papers=[
            page(APS),
            page("https://journals.aps.org/prl/abstract/10.1103/nope"),
            page("https://ieeexplore.ieee.org/document/10242110"),
            page(APS, kind="article-journal"),
        ],
    )
    web_pages.complete(export, None)  # offline: nothing looked up
    assert not any(p.looked_up for p in export.papers)

    web_pages.complete(export, http, pause=0)
    found, unknown, other, article = export.papers
    assert found.looked_up and found.csl["title"] == "Hole spin qubits"
    assert found.csl["type"] == "journal-article" and found.csl["URL"] == APS
    assert found.identifiers == [(Scheme.DOI, DOI)]
    for kept in (unknown, other, article):
        assert not kept.looked_up and kept.csl["title"] == kept.csl["URL"]
    assert len(doi_registry.requests) == 2

    # doi.org does not answer: the rest stay web pages.
    down = httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(503)))
    again = Export(format="zotero-rdf", papers=[page(APS)])
    web_pages.complete(again, down, pause=0)
    assert again.papers[0].csl["type"] == "webpage"


RDF = f"""<rdf:RDF
 xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:z="http://www.zotero.org/namespaces/export#"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:bib="http://purl.org/net/biblio#"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
    <bib:Document rdf:about="{APS}">
        <z:itemType>webpage</z:itemType>
        <dc:title>{APS}</dc:title>
        <dc:identifier>
            <dcterms:URI><rdf:value>{APS}</rdf:value></dcterms:URI>
        </dc:identifier>
    </bib:Document>
</rdf:RDF>"""


def test_imported_from_zotero(
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    doi_registry: FakeDOIRegistry,
) -> None:
    [web_page] = zotero.read(RDF).papers
    assert web_page.csl["type"] == "webpage"
    # Known by its DOI already: a paper one has is recognised.
    assert web_page.identifiers == [(Scheme.DOI, DOI)]

    ada = Person(client, db, "ada")
    doi_registry.records[DOI] = {"type": "journal-article", "title": "Hole spins"}
    started = client.post(
        "/api/imports",
        headers=ada.headers,
        files={"upload": ("Exported Items.rdf", RDF.encode())},
    ).json()
    record = db.get(Import, uuid.UUID(started["id"]))
    assert record is not None and record.blob_sha256 is not None
    with blobs.local_file(record.blob_sha256) as path:
        run_import(
            db,
            blobs,
            record,
            path=path,
            max_file_bytes=10_000_000,
            http=httpx2.Client(transport=httpx2.MockTransport(doi_registry)),
        )
    [item] = ada.get("/api/items").json()
    assert (item["type"], item["title"]) == ("article-journal", "Hole spins")
    paper = db.get(Item, uuid.UUID(item["id"]))
    assert paper is not None
    assert paper.versions[0].metadata_source == MetadataSource.LOOKUP
