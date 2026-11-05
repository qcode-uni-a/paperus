"""Personal access tokens: scopes, owner limits, expiry, revoking."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from paperus.models import AccessToken
from paperus.tokens import needed_scope
from tests.people import Person, group


def make_token(person: Person, **body: object) -> dict[str, Any]:
    response = person.post("/api/me/tokens", json={"name": "test", **body})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def as_token(client: TestClient, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_scopes(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper = ada.add("A paper")
    reader = make_token(ada, scopes=["search", "papers.read"])
    assert reader["token"].startswith("paperus_")
    assert reader["hint"] == reader["token"][:12] + "…"
    headers = as_token(client, reader["token"])
    client.cookies.clear()
    assert client.get("/api/items", headers=headers).json()[0]["title"] == "A paper"
    assert client.get(f"/api/items/{paper['id']}", headers=headers).status_code == 200
    # Not allowed by its scopes.
    assert (
        client.post(
            "/api/items", headers=headers, json={"metadata": {"title": "x"}}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/items/{paper['id']}/tags", headers=headers, json={"name": "t"}
        ).status_code
        == 403
    )
    # Never with a token: account, tokens, administration, groups.
    for method, url in [
        ("GET", "/api/me/tokens"),
        ("POST", "/api/me/tokens"),
        ("POST", "/api/auth/password"),
        ("GET", "/api/admin/users"),
        ("POST", "/api/groups"),
        ("PUT", "/api/me/default-library"),
    ]:
        assert client.request(method, url, headers=headers, json={}).status_code == 403
    writer = make_token(ada, scopes=["papers.write", "tags.write"])
    headers = as_token(client, writer["token"])
    assert (
        client.post(
            "/api/items", headers=headers, json={"metadata": {"title": "By a script"}}
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/items/{paper['id']}/tags", headers=headers, json={"name": "t"}
        ).status_code
        == 201
    )


def test_owner_limit(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    chair = group(root, "Chair", ada)
    ada.add("Private")
    ada.add("Shared", chair["library_id"])
    only_chair = make_token(
        ada, scopes=["papers.read", "papers.write"], library_ids=[chair["library_id"]]
    )
    headers = as_token(client, only_chair["token"])
    client.cookies.clear()
    titles = [i["title"] for i in client.get("/api/items", headers=headers).json()]
    assert titles == ["Shared"]
    # New papers go to the one owner it may use.
    added = client.post(
        "/api/items", headers=headers, json={"metadata": {"title": "New"}}
    ).json()
    assert added["library_id"] == chair["library_id"]
    # Only owners one belongs to.
    other = make_token(root, scopes=["papers.read"])  # root is in no group
    assert other["library_ids"] is None
    response = root.post(
        "/api/me/tokens",
        json={
            "name": "x",
            "scopes": ["papers.read"],
            "library_ids": [chair["library_id"]],
        },
    )
    assert response.status_code == 422


def test_expiry_revoking_and_deactivation(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    token = make_token(ada, scopes=["papers.read"], expires_in_days=30)
    headers = as_token(client, token["token"])
    assert client.get("/api/items", headers=headers).status_code == 200
    listed = ada.get("/api/me/tokens").json()
    assert listed[0]["last_used_at"] is not None
    assert "token" not in listed[0]  # never shown again

    db.execute(
        update(AccessToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    assert client.get("/api/items", headers=headers).status_code == 401

    fresh = make_token(ada, scopes=["papers.read"])
    headers = as_token(client, fresh["token"])
    root.client.patch(
        f"/api/admin/users/{ada.id}", headers=root.headers, json={"active": False}
    )
    assert client.get("/api/items", headers=headers).status_code == 401
    root.client.patch(
        f"/api/admin/users/{ada.id}", headers=root.headers, json={"active": True}
    )
    assert client.get("/api/items", headers=headers).status_code == 200
    assert ada.delete(f"/api/me/tokens/{fresh['id']}").status_code == 401  # logged out
    login = client.post(
        "/api/auth/login", json={"username": "ada", "password": "secret"}
    )
    session = {"Authorization": f"Bearer {login.json()['token']}"}
    assert (
        client.delete(f"/api/me/tokens/{fresh['id']}", headers=session).status_code
        == 204
    )
    assert client.get("/api/items", headers=headers).status_code == 401


def test_scope_table() -> None:
    assert needed_scope("GET", "/api/search") == "search"
    assert needed_scope("GET", "/api/files/x/content") == "files.read"
    assert needed_scope("DELETE", "/api/items/x") == "papers.write"
    assert needed_scope("POST", "/api/items/x/tags") == "tags.write"
    assert needed_scope("PATCH", "/api/collections/x") == "collections.write"
    assert needed_scope("GET", "/api/groups") == "groups.read"
    assert needed_scope("PATCH", "/api/groups/x") is None
    assert needed_scope("GET", "/api/admin/backups") is None
