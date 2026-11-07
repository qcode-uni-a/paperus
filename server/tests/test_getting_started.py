"""Getting started: the first steps, each marked done once taken."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import FakeML
from tests.people import Person
from tests.test_import import zip_bytes
from tests.test_tokens import as_token, make_token

BIB = "@article{a, title={Radar gaps over the Alps}, year={2020}}\n"


def test_a_persons_steps(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    steps = ada.get("/api/me/getting-started").json()
    assert steps == {
        "papers": False,
        "imported": False,
        "extension": False,
        "assistant": False,
        "server": None,
    }

    ada.add("Floquet qubits")
    upload = zip_bytes(**{"My Library/My Library.bib": BIB.encode()})
    response = client.post(
        "/api/imports",
        headers=ada.headers,
        files={"upload": ("My Library.zip", upload, "application/zip")},
    )
    assert response.status_code == 201, response.text
    extension = make_token(
        ada, name="Browser extension (Firefox)", scopes=["papers.write"]
    )
    steps = ada.get("/api/me/getting-started").json()
    assert (steps["papers"], steps["imported"], steps["extension"]) == (
        True,
        True,
        True,
    )
    # The extension's token is no AI assistant.
    assert steps["assistant"] is False
    make_token(ada, name="Claude Desktop", scopes=["search"])
    assert ada.get("/api/me/getting-started").json()["assistant"] is True

    # Only in person: a token never asks.
    client.cookies.clear()
    response = client.get(
        "/api/me/getting-started", headers=as_token(client, extension["token"])
    )
    assert response.status_code == 403


def test_the_servers_steps(client: TestClient, db: Session, fake_ml: FakeML) -> None:
    root = Person(client, db, "root", admin=True)
    server = root.get("/api/me/getting-started").json()["server"]
    # Daily backups (of the database) from the start.
    assert server == {
        "backups": True,
        "contact_email": False,
        "search": True,
        "people": False,
    }

    response = root.put(
        "/api/admin/backups/config",
        json={"schedule": "off", "hour": 3, "with_files": False, "keep": 7},
    )
    assert response.status_code == 200, response.text
    config = root.get("/api/admin/config").json()
    response = root.put(
        "/api/admin/config", json={**config, "contact_email": "library@example.org"}
    )
    assert response.status_code == 200, response.text
    Person(client, db, "ada")
    fake_ml.down = True
    server = root.get("/api/me/getting-started").json()["server"]
    assert server == {
        "backups": False,
        "contact_email": True,
        "search": False,
        "people": True,
    }
