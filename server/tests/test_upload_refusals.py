"""Uploads that are refused, and one whose reading cannot be queued."""

from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy.orm import Session

from paperus.app import create_app
from paperus.config import Settings
from paperus.jobs import tasks
from paperus.models import File, TextStatus
from tests.conftest import FakeDOIRegistry, FakeML
from tests.pdfs import make_pdf
from tests.people import Person

PDF = make_pdf([["Rainfall at the old station"]])


def upload(person: Person, url: str, data: bytes = PDF) -> Any:  # noqa: ANN401
    return person.post(url, files={"upload": ("paper.pdf", data, "application/pdf")})


def test_no_uploads_to_trashed_or_empty_papers(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("In the trash")
    version = paper["versions"][0]["id"]
    assert ada.delete(f"/api/items/{paper['id']}").status_code == 204
    for url in (f"/api/versions/{version}/files", f"/api/items/{paper['id']}/files"):
        refused = upload(ada, url)
        assert refused.status_code == 409, url
        assert refused.json()["detail"] == "item is in the trash"

    # A paper merged into another and taken back out of the trash has no
    # version left to hold a file.
    away, keep = ada.add("Twice"), ada.add("Twice")
    merged = ada.post(f"/api/items/{away['id']}/merge", {"into": keep["id"]})
    assert merged.status_code == 200, merged.text
    assert ada.post(f"/api/items/{away['id']}/restore").status_code == 200
    empty = upload(ada, f"/api/items/{away['id']}/files")
    assert empty.status_code == 409
    assert empty.json()["detail"] == "item has no version"


class Unreachable(InMemoryConnector):
    """A job queue that is down."""

    async def defer_jobs_all(self, jobs: Any) -> Any:  # noqa: ANN401
        raise ConnectionError("job queue unreachable")


@pytest.fixture
def queue_down(
    settings: Settings,
    db: Session,
    doi_registry: FakeDOIRegistry,
    fake_ml: FakeML,
) -> Iterator[TestClient]:
    jobs = App(connector=Unreachable())
    jobs.add_tasks_from(tasks, namespace="paperus")
    app = create_app(
        settings,
        http_client=httpx2.Client(transport=httpx2.MockTransport(doi_registry)),
        job_app=jobs,
        ml_client=fake_ml.client(),
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def test_upload_while_the_queue_is_down(queue_down: TestClient, db: Session) -> None:
    ada = Person(queue_down, db, "ada")
    paper = ada.add("A paper")
    added = upload(ada, f"/api/items/{paper['id']}/files")
    # Kept all the same: the worker's sweep reads it later.
    assert added.status_code == 201, added.text
    file = db.get(File, added.json()["id"])
    assert file is not None
    assert file.text_status == TextStatus.PENDING
