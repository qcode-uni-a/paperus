"""Personal access tokens: scopes, owner limits, expiry, revoking."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
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


def test_owner_limit_holds_everywhere(client: TestClient, db: Session) -> None:
    """A token limited to a group reaches none of the person's private
    things, not by id, not with ?library=, not as notes or files."""
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    chair = group(root, "Chair", ada)
    private = ada.add("Private")
    own = ada.libraries()["Me"]["id"]
    file = ada.post(
        f"/api/items/{private['id']}/files",
        files={"upload": ("p.pdf", b"%PDF-1.7\n" + b"x" * 3000, "application/pdf")},
    ).json()
    note = ada.note("Private note")
    token = make_token(
        ada,
        scopes=["papers.read", "files.read", "search", "groups.read"],
        library_ids=[chair["library_id"]],
    )
    headers = as_token(client, token["token"])
    client.cookies.clear()
    get = lambda path: client.get(path, headers=headers)  # noqa: E731
    assert get(f"/api/items/{private['id']}").status_code == 404
    assert get(f"/api/items?library={own}").json() == []
    assert get(f"/api/search?q=private&library={own}").json() == []
    assert get(f"/api/notes/{note['id']}").status_code == 404
    assert get(f"/api/files/{file['id']}/content").status_code == 404
    # The libraries it may use: the group only (even read-only tokens).
    assert [lib["name"] for lib in get("/api/libraries").json()] == ["Chair"]


def test_admin_tokens_get_no_administration(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    group(root, "Chair", ada)
    group(root, "Lab", root)
    # In person, a site admin sees every group; through a token, only theirs.
    assert len(root.get("/api/groups").json()) == 2
    token = make_token(root, scopes=["groups.read"])
    client.cookies.clear()
    groups = client.get("/api/groups", headers=as_token(client, token["token"]))
    assert [g["name"] for g in groups.json()] == ["Lab"]


# What an access token may call: every API route, with the scope it needs
# (None: never with a token). A new route fails this test until its line is
# added here, so opening one to tokens is always a decision.
ROUTES = {
    ("GET", "/api/admin/backups"): None,
    ("POST", "/api/admin/backups"): None,
    ("PUT", "/api/admin/backups/config"): None,
    ("DELETE", "/api/admin/backups/{name}"): None,
    ("GET", "/api/admin/config"): None,
    ("PUT", "/api/admin/config"): None,
    ("GET", "/api/admin/integrity"): None,
    ("POST", "/api/admin/jobs/{job}"): None,
    ("GET", "/api/admin/ml"): None,
    ("DELETE", "/api/admin/ml/models/{name}"): None,
    ("POST", "/api/admin/ml/models/{name}/speed"): None,
    ("GET", "/api/admin/stats"): None,
    ("GET", "/api/admin/users"): None,
    ("POST", "/api/admin/users"): None,
    ("PATCH", "/api/admin/users/{user_id}"): None,
    ("PUT", "/api/auth/hints/{hint}"): None,
    ("POST", "/api/auth/login"): None,
    ("GET", "/api/auth/methods"): None,
    ("GET", "/api/auth/oidc/start"): None,
    ("GET", "/api/auth/oidc/callback"): None,
    ("DELETE", "/api/auth/oidc/link"): None,
    ("GET", "/api/admin/authentication"): None,
    ("PUT", "/api/admin/authentication/secret"): None,
    ("POST", "/api/admin/authentication/check"): None,
    ("DELETE", "/api/admin/sessions"): None,
    ("PUT", "/api/me/avatar"): None,
    ("DELETE", "/api/me/avatar"): None,
    ("GET", "/api/users/{user_id}/avatar"): None,
    ("GET", "/api/admin/readable-copy"): None,
    ("POST", "/api/admin/readable-copy/preview"): None,
    ("GET", "/api/admin/users/{user_id}/private"): None,
    ("POST", "/api/admin/users/{user_id}/hand-over"): None,
    ("POST", "/api/auth/logout"): None,
    ("GET", "/api/auth/me"): "papers.read",
    ("POST", "/api/auth/password"): None,
    ("GET", "/api/citations"): "papers.read",
    ("GET", "/api/collections"): "papers.read",
    ("POST", "/api/collections"): "collections.write",
    ("DELETE", "/api/collections/{collection_id}"): "collections.write",
    ("PATCH", "/api/collections/{collection_id}"): "collections.write",
    ("POST", "/api/collections/{collection_id}/items"): "collections.write",
    ("DELETE", "/api/collections/{collection_id}/items/{item_id}"): "collections.write",
    ("GET", "/api/collections/{collection_id}/move-preview"): "papers.read",
    ("POST", "/api/collections/{collection_id}/notes"): "collections.write",
    ("DELETE", "/api/collections/{collection_id}/notes/{note_id}"): "collections.write",
    ("DELETE", "/api/collections/{collection_id}/pin"): None,
    ("PUT", "/api/collections/{collection_id}/pin"): None,
    ("GET", "/api/duplicates"): "papers.read",
    ("POST", "/api/duplicates/different"): None,
    ("DELETE", "/api/files/{file_id}"): "papers.write",
    ("GET", "/api/files/{file_id}/passages/{position}"): "papers.read",
    ("GET", "/api/files/unreadable"): None,
    ("POST", "/api/files/{file_id}/read-again"): "papers.write",
    ("POST", "/api/files/{file_id}/download-again"): "papers.write",
    ("GET", "/api/files/{file_id}/content"): "files.read",
    ("POST", "/api/files/{file_id}/restore"): "papers.write",
    ("GET", "/api/groups"): "groups.read",
    ("POST", "/api/groups"): None,
    ("DELETE", "/api/groups/{group_id}"): None,
    ("PATCH", "/api/groups/{group_id}"): None,
    ("POST", "/api/groups/{group_id}/leave"): None,
    ("GET", "/api/groups/{group_id}/members"): "groups.read",
    ("DELETE", "/api/groups/{group_id}/members/{user_id}"): None,
    ("PUT", "/api/groups/{group_id}/members/{user_id}"): None,
    ("GET", "/api/health"): None,
    ("GET", "/api/health/db"): None,
    ("GET", "/api/imports"): None,
    ("POST", "/api/imports"): None,
    ("GET", "/api/imports/{import_id}"): None,
    ("GET", "/api/items"): "papers.read",
    ("POST", "/api/items"): "papers.write",
    ("DELETE", "/api/items/{item_id}"): "papers.write",
    ("GET", "/api/items/lookup"): "papers.read",
    ("GET", "/api/items/{item_id}"): "papers.read",
    ("GET", "/api/items/{item_id}/duplicates"): "papers.read",
    ("DELETE", "/api/items/{item_id}/favourite"): None,
    ("PUT", "/api/items/{item_id}/favourite"): None,
    ("POST", "/api/items/{item_id}/files"): "papers.write",
    ("POST", "/api/items/{item_id}/merge"): "papers.write",
    ("GET", "/api/items/{item_id}/merge-preview"): "papers.read",
    ("PUT", "/api/items/{item_id}/overrides"): "papers.write",
    ("PUT", "/api/items/{item_id}/owner"): "papers.write",
    ("POST", "/api/items/{item_id}/restore"): "papers.write",
    ("POST", "/api/items/{item_id}/tags"): "tags.write",
    ("DELETE", "/api/items/{item_id}/tags/{tag_id}"): "tags.write",
    ("POST", "/api/items/{item_id}/versions"): "papers.write",
    ("POST", "/api/items/{item_id}/viewed"): None,
    ("GET", "/api/libraries"): "groups.read",
    ("PUT", "/api/me/default-library"): None,
    ("GET", "/api/me/tokens"): None,
    ("POST", "/api/me/tokens"): None,
    ("DELETE", "/api/me/tokens/{token_id}"): None,
    ("GET", "/api/notes"): "papers.read",
    ("POST", "/api/notes"): "notes.write",
    ("DELETE", "/api/notes/{note_id}"): "notes.write",
    ("GET", "/api/notes/{note_id}"): "papers.read",
    ("PATCH", "/api/notes/{note_id}"): "notes.write",
    ("GET", "/api/notes/{note_id}/history"): "papers.read",
    ("DELETE", "/api/notes/{note_id}/items/{item_id}"): "notes.write",
    ("PUT", "/api/notes/{note_id}/items/{item_id}"): "notes.write",
    ("GET", "/api/notes/{note_id}/markdown"): "papers.read",
    ("PUT", "/api/notes/{note_id}/owner"): "notes.write",
    ("POST", "/api/notes/{note_id}/restore"): "notes.write",
    ("GET", "/api/search"): "search",
    ("GET", "/api/setup"): None,
    ("POST", "/api/setup/admin"): None,
    ("POST", "/api/setup/restore"): None,
    ("GET", "/api/setup/restore-check"): None,
    ("GET", "/api/tags"): "papers.read",
    ("POST", "/api/tags"): "tags.write",
    ("DELETE", "/api/tags/{tag_id}"): "tags.write",
    ("PATCH", "/api/tags/{tag_id}"): "tags.write",
    ("GET", "/api/storage"): None,
    ("DELETE", "/api/trash"): None,
    ("POST", "/api/uploads"): "papers.write",
    ("GET", "/api/uploads/{sha256}"): "papers.read",
    ("GET", "/api/users"): None,
    ("POST", "/api/versions/{version_id}/files"): "papers.write",
    ("POST", "/api/versions/{version_id}/pin"): "papers.write",
}


def test_every_route_has_a_decision(client: TestClient) -> None:
    app = client.app
    assert isinstance(app, FastAPI)
    found = {}
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api"):
            continue
        concrete = re.sub(r"\{[^}]+\}", "x", path)
        for method in operations:
            scope = needed_scope(method.upper(), concrete)
            found[(method.upper(), path)] = scope.value if scope else None
    assert found == ROUTES
