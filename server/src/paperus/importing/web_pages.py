"""Papers saved as web pages: when Zotero could not get a paper's PDF (a
publisher blocked it), it kept the journal's page instead, titled like the
page ("Gauge principle … | Phys. Rev. A") or by its address. With a DOI in
the address (``journals.aps.org/prb/pdf/10.1103/PhysRevB.104.035302``), the
import looks up the paper's details: the web page comes in as the paper,
whose open-access copy, reference list and authors are then looked for.
"""

import logging
import re
from urllib.parse import unquote

import httpx2

from paperus import metadata
from paperus.identifiers import InvalidIdentifier, Scheme, implied_by_doi, normalize_doi
from paperus.importing import Export
from paperus.importing.references import PAUSE, Pacer

log = logging.getLogger(__name__)

# A DOI as a part of the path, up to the query: "…/abstract/10.1103/…",
# "doi.org/10.1038/…", "…/doi/pdf/10.1002/…".
_DOI_IN_PATH = re.compile(r"/(10\.\d{4,9}/[^?#\s]+)")
_TRAILING = re.compile(r"(?:/(?:full|abstract|pdf|epdf|html|meta))*(?:\.pdf)?/*$", re.I)


def doi_in_address(url: str | None) -> str | None:
    """The DOI in a web address (a journal's page of a paper), if any."""
    found = _DOI_IN_PATH.search(unquote(url or ""))
    if found is None:
        return None
    try:
        return normalize_doi(_TRAILING.sub("", found.group(1)))
    except InvalidIdentifier:
        return None


def complete(
    export: Export, http: httpx2.Client | None, *, pause: float | None = None
) -> None:
    """The details of the export's web pages with a DOI in their address
    (see the module); the others stay as they are. Without ``http``, or
    while doi.org does not answer, nothing is looked up."""
    if http is None:
        return
    pacer = Pacer(PAUSE if pause is None else pause)
    for paper in export.papers:
        if paper.csl.get("type") != "webpage":
            continue
        doi = doi_in_address(paper.csl.get("URL"))
        if doi is None:
            continue
        pacer()
        try:
            csl, _ = metadata.lookup_doi(http, doi)
        except metadata.DOINotFound:
            log.info("web page %s: no paper has the DOI %s", paper.csl["URL"], doi)
            continue
        except metadata.MetadataUnavailable:
            return
        paper.csl = {**csl, "URL": csl.get("URL") or paper.csl["URL"]}
        paper.identifiers = list(
            dict.fromkeys([(Scheme.DOI, doi), *implied_by_doi(doi), *paper.identifiers])
        )
        paper.looked_up = True
