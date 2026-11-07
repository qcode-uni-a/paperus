"""What the API refuses, and with which answer: unknown things, empty names,
other people's things, and papers added by someone else meanwhile."""

import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.requests import Request

from paperus import library
from paperus.api.deps import session_user
from paperus.models import User
from tests.people import Person, group

NOBODY = str(uuid.uuid4())
ISBN = {"scheme": "isbn", "value": "978-0-306-40615-7"}


def status(response: Any) -> int:  # noqa: ANN401 (a response)
    code: int = response.status_code
    return code


@pytest.fixture
def root(client: TestClient, db: Session) -> Person:
    return Person(client, db, "root", admin=True)


@pytest.fixture
def ada(client: TestClient, db: Session) -> Person:
    return Person(client, db, "ada")


def test_unknown_things(root: Person, ada: Person) -> None:
    paper = ada.add("A paper")
    for method, url, body in [
        ("POST", f"/api/versions/{NOBODY}/pin", None),
        ("PUT", f"/api/items/{NOBODY}/overrides", {}),
        ("POST", f"/api/items/{NOBODY}/tags", {"name": "t"}),
        ("PATCH", f"/api/tags/{NOBODY}", {"name": "t"}),
        ("POST", f"/api/versions/{NOBODY}/files", None),
        ("DELETE", f"/api/me/tokens/{NOBODY}", None),
        ("PATCH", f"/api/admin/users/{NOBODY}", {"active": False}),
        ("GET", f"/api/admin/users/{NOBODY}/private", None),
        ("POST", f"/api/admin/users/{NOBODY}/hand-over", {"user_id": ada.id}),
        ("PUT", f"/api/groups/{NOBODY}/members/{ada.id}", {"role": "member"}),
    ]:
        response = root.client.request(
            method,
            url,
            headers={**root.headers, "If-Match": '"0"'},
            json=body,
            files={"upload": ("a.pdf", b"%PDF-", "application/pdf")}
            if url.endswith("/files")
            else None,
        )
        assert status(response) == 404, (method, url, response.text)
    # Someone else's paper is unknown too.
    version = paper["versions"][0]["id"]
    assert status(root.post(f"/api/versions/{version}/pin")) == 404
    assert status(root.post(f"/api/items/{paper['id']}/tags", {"name": "t"})) == 404


def test_empty_names(root: Person, ada: Person) -> None:
    paper = ada.add("A paper")
    tag = ada.post("/api/tags", {"name": "rain"}).json()
    collection = ada.post("/api/collections", {"name": "Reading"}).json()
    chair = group(root, "Chair", ada)
    for method, url in [
        ("POST", "/api/tags"),
        ("POST", f"/api/items/{paper['id']}/tags"),
        ("PATCH", f"/api/tags/{tag['id']}"),
        ("POST", "/api/collections"),
        ("PATCH", f"/api/collections/{collection['id']}"),
        ("POST", "/api/groups"),
        ("PATCH", f"/api/groups/{chair['id']}"),
    ]:
        person = root if url == "/api/groups" else ada
        response = person.client.request(
            method, url, headers=person.headers, json={"name": "  "}
        )
        assert status(response) == 422, (method, url, response.text)
        assert "must not be empty" in response.text


def test_wrong_requests_to_items(ada: Person) -> None:
    paper = ada.add("A paper")
    url = f"/api/items/{paper['id']}/overrides"
    garbled = ada.client.put(
        url, headers={**ada.headers, "If-Match": "yesterday"}, json={}
    )
    assert status(garbled) == 412
    itself = ada.get(f"/api/items/{paper['id']}/merge-preview?into={paper['id']}")
    assert status(itself) == 409
    assert "into itself" in itself.json()["detail"]
    # Several journal names: the first; none: no journal.
    for names, shown in ((["Nature", "Nat."], "Nature"), ([], None)):
        response = ada.post(
            "/api/items",
            {"metadata": {"title": f"In {names}", "container-title": names}},
        )
        assert response.json()["container_title"] == shown


def test_added_by_someone_else_meanwhile(
    ada: Person, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first look for a known identifier misses one added just then; the
    second, while adding, finds it."""
    first = ada.post(
        "/api/items", {"metadata": {"title": "First"}, "identifiers": [ISBN]}
    )
    other = ada.add("Other")
    find = library.find_identifier
    looks: list[int] = []

    def missing_once(*args: Any) -> Any:  # noqa: ANN401
        looks.append(1)
        return None if len(looks) == 1 else find(*args)

    monkeypatch.setattr(library, "find_identifier", missing_once)
    again = ada.post(
        "/api/items", {"metadata": {"title": "Again"}, "identifiers": [ISBN]}
    )
    assert status(again) == 409
    assert again.json()["detail"]["item_id"] == first.json()["id"]
    looks.clear()
    version = ada.post(
        f"/api/items/{other['id']}/versions",
        {"metadata": {"title": "Again"}, "identifiers": [ISBN]},
    )
    assert status(version) == 409
    assert version.json()["detail"]["item_id"] == first.json()["id"]


def test_tags_elsewhere(root: Person, ada: Person, db: Session) -> None:
    ben = Person(root.client, db, "ben")
    paper = ada.add("A paper")
    # A tag of a library one cannot see.
    response = ada.post(
        f"/api/items/{paper['id']}/tags",
        {"name": "t", "library_id": ben.libraries()["Me"]["id"]},
    )
    assert status(response) == 404, response.text
    # Giving a tag to an owner that has one of that name.
    chair = group(root, "Chair", ada)
    ada.post("/api/tags", {"name": "rain", "library_id": chair["library_id"]})
    mine = ada.post("/api/tags", {"name": "Rain"}).json()
    moved = ada.patch(f"/api/tags/{mine['id']}", {"library_id": chair["library_id"]})
    assert status(moved) == 409


def test_groups_and_members(root: Person, ada: Person) -> None:
    unknown_admin = root.post("/api/groups", {"name": "Lab", "admin_id": NOBODY})
    assert status(unknown_admin) == 422
    chair = group(root, "Chair", ada)
    project = group(ada, "Project", ada, parent=chair["id"])
    members = f"/api/groups/{chair['id']}/members"
    assert status(ada.put(f"{members}/{NOBODY}", {"role": "member"})) == 404
    # Only direct members can be removed here.
    inherited = f"/api/groups/{project['id']}/members/{ada.id}"
    assert status(ada.delete(inherited)) == 404
    # A group inside another may lose its last own admin (the parent's stay).
    assert status(ada.put(inherited, {"role": "admin"})) == 200
    assert status(ada.delete(inherited)) == 200


def test_people_administration(root: Person, ada: Person) -> None:
    deactivate_self = root.patch(f"/api/admin/users/{root.id}", {"active": False})
    # Another active administrator is needed first, then oneself is refused.
    assert status(deactivate_self) == 409
    root.patch(f"/api/admin/users/{ada.id}", {"is_admin": True})
    assert (
        "yourself"
        in root.patch(f"/api/admin/users/{root.id}", {"active": False}).json()["detail"]
    )

    root.patch(f"/api/admin/users/{ada.id}", {"active": False})
    to_nowhere = root.post(f"/api/admin/users/{ada.id}/hand-over", {"group_id": NOBODY})
    assert status(to_nowhere) == 404
    assert to_nowhere.json()["detail"] == "group not found"


def test_where_new_papers_go(root: Person, ada: Person) -> None:
    chair = group(root, "Chair", root)
    root.put(f"/api/groups/{chair['id']}/members/{ada.id}", {"role": "member"})
    assert (
        status(ada.put("/api/me/default-library", {"library_id": chair["library_id"]}))
        == 204
    )
    assert ada.add("For the chair")["library_id"] == chair["library_id"]
    # Out of the group: back to one's own library.
    assert status(root.delete(f"/api/groups/{chair['id']}/members/{ada.id}")) == 200
    assert ada.add("Mine")["library_id"] == ada.libraries()["Me"]["id"]

    # A token for a group one only reads adds nothing.
    root.put(f"/api/groups/{chair['id']}/members/{ada.id}", {"role": "reader"})
    token = ada.post(
        "/api/me/tokens",
        {
            "name": "reader",
            "scopes": ["papers.write", "groups.read"],
            "library_ids": [chair["library_id"]],
        },
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    added = ada.client.post(
        "/api/items", headers=headers, json={"metadata": {"title": "No"}}
    )
    assert status(added) == 403
    libraries = ada.client.get("/api/libraries", headers=headers).json()
    assert [(lib["name"], lib["default"]) for lib in libraries] == [("Chair", False)]


def test_account_routes_never_with_a_token(ada: Person) -> None:
    """Even if a token's scopes let it reach one (they do not)."""
    request = Request({"type": "http", "state": {"access_token": object()}})
    with pytest.raises(HTTPException) as refused:
        session_user(request, User(username="ada"))
    assert refused.value.status_code == 403


def test_collections_and_owners_unchanged(ada: Person) -> None:
    paper = ada.add("A paper")
    reading = ada.post("/api/collections", {"name": "Reading"}).json()
    smart = ada.post(
        "/api/collections", {"name": "Recent", "rules": {"year_from": 2020}}
    ).json()
    inside = ada.patch(f"/api/collections/{reading['id']}", {"parent_id": smart["id"]})
    assert inside.status_code == 409
    assert inside.json()["detail"] == "a smart collection holds no other collections"
    # Added twice: held once.
    url = f"/api/collections/{reading['id']}/items"
    for _ in range(2):
        assert ada.post(url, {"item_ids": [paper["id"]]}).json()["count"] == 1
    # Given to the owner it has: nothing changes.
    own = ada.libraries()["Me"]["id"]
    kept = ada.put(f"/api/items/{paper['id']}/owner", {"library_id": own})
    assert kept.status_code == 200
    assert ada.titles(collection_id=reading["id"]) == ["A paper"]
