"""Cover pages a site put in front of or behind a paper (#42)."""

import textwrap
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.covers import cover_pages, is_cover
from paperus.models import File
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.pdfs import make_pdf
from tests.people import Person
from tests.test_processing import passages, upload

# As IOP's cover reads (from a paper of the development library).
IOP = (
    "PAPER • OPEN ACCESS Exact Floquet flat band and heating suppression via "
    "two-tone drive protocols To cite this article: Tista Banerjee et al 2025 "
    "New J. Phys. 27 084506 View the article online for updates and "
    "enhancements. You may also like Waveguides in a quantum dot array"
)
# A university repository's sheet in front of a thesis.
THESIS = (
    "Spin-orbit interactions in low-dimensional semiconductor holes Author: "
    "Marcellina, Elizabeth Publication Date: 2017 DOI: "
    "https://doi.org/10.26190/unsworks/3311 License: "
    "https://creativecommons.org/licenses/by-nc-nd/3.0/au/ Link to license "
    "to see what you are allowed to do with this resource."
)
# A Pure repository's: none of the sources' own phrases, two shared ones.
PURE = (
    "Citation for published version (APA): Doe, J. (2020). Rain. General "
    "rights Copyright and moral rights for the publications made accessible "
    "in the public portal are retained by the authors."
)
PAPER = "Ultrastrong coupling of the cyclotron transition. " + "We find " * 400


def test_what_a_cover_is() -> None:
    assert is_cover(IOP) and is_cover(THESIS) and is_cover(PURE)
    # A paper's page saying where it was downloaded from is no cover: long.
    assert not is_cover(PAPER + " Downloaded from https://www.science.org")
    # One shared phrase alone is not enough; nor nothing.
    assert not is_cover("Terms of use apply. A short note on rain.")
    assert not is_cover("")
    # The first page, the last of a longer file; never a file's only page.
    assert cover_pages([IOP, PAPER]) == [1]
    assert cover_pages([PAPER, PAPER, PURE]) == [3]
    assert cover_pages([PAPER, PURE]) == []
    assert cover_pages([IOP]) == []


def test_a_cover_is_left_out_of_the_text(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    ada = Person(client, db, "ada")
    # In lines, as on a page (the test PDFs do not wrap them).
    cover = textwrap.wrap(IOP.replace("•", "-"), 70)
    content = make_pdf([cover, ["Exact Floquet flat band", "The paper itself."]])
    file_id = upload(ada, "iop.pdf", content, "application/pdf")
    process_file(db, blobs, file_id)
    file = db.get(File, file_id)
    assert file is not None and file.cover_pages == [1]
    text = " ".join(passages(db, file_id))
    assert "The paper itself" in text and "To cite this article" not in text
    files = ada.get(f"/api/items/{_item(db, file_id)}").json()["versions"][0]["files"]
    assert files[0]["cover_pages"] == [1]
    # A copy of the same file takes it over without reading it again.
    copy = upload(ada, "again.pdf", content, "application/pdf")
    process_file(db, blobs, copy)
    again = db.get(File, copy)
    assert again is not None and again.cover_pages == [1]


def _item(db: Session, file_id: uuid.UUID) -> uuid.UUID:
    file = db.get(File, file_id)
    assert file is not None
    return file.version.item_id
