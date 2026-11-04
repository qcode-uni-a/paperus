"""Change numbers, syncing, edits with If-Match, and the trash."""

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import FakeDOIRegistry

PDF = b"%PDF-1.7\n%%EOF\n"


def add(client: TestClient, title: str) -> dict[str, Any]:
    response = client.post("/api/items", json={"metadata": {"title": title}})
    assert response.status_code == 201
    result: dict[str, Any] = response.json()
    return result


def get(client: TestClient, item_id: str) -> dict[str, Any]:
    result: dict[str, Any] = client.get(f"/api/items/{item_id}").json()
    return result


def last_change(client: TestClient) -> int:
    return int(client.get("/api/items").headers["Last-Change"])


def test_every_change_gets_a_new_number(logged_in: TestClient) -> None:
    item = add(logged_in, "Notes")
    assert item["change"] == 1 == last_change(logged_in)

    version_id = item["versions"][0]["id"]
    upload = logged_in.post(
        f"/api/versions/{version_id}/files",
        files={"upload": ("a.pdf", PDF, "application/pdf")},
    )
    assert get(logged_in, item["id"])["change"] == 2

    logged_in.delete(f"/api/files/{upload.json()['id']}")
    assert get(logged_in, item["id"])["change"] == 3

    logged_in.post(
        f"/api/items/{item['id']}/versions",
        json={"metadata": {"title": "Notes v2"}, "kind": "edition"},
    )
    assert get(logged_in, item["id"])["change"] == 4

    # Reading changes nothing.
    get(logged_in, item["id"])
    logged_in.get("/api/items")
    assert last_change(logged_in) == 4


def test_sync_since(logged_in: TestClient) -> None:
    a = add(logged_in, "A")
    b = add(logged_in, "B")
    since = last_change(logged_in)
    assert logged_in.get("/api/items", params={"since": since}).json() == []

    logged_in.delete(f"/api/items/{a['id']}")
    c = add(logged_in, "C")
    changed = logged_in.get("/api/items", params={"since": since}).json()
    assert [item["id"] for item in changed] == [a["id"], c["id"]]
    assert changed[0]["deleted_at"] is not None

    everything = logged_in.get("/api/items", params={"since": 0}).json()
    assert {item["id"] for item in everything} == {a["id"], b["id"], c["id"]}


def test_overrides_need_current_etag(logged_in: TestClient) -> None:
    item = add(logged_in, "Draft title")
    url = f"/api/items/{item['id']}/overrides"
    etag = logged_in.get(f"/api/items/{item['id']}").headers["ETag"]
    assert etag == f'"{item["change"]}"'

    assert logged_in.put(url, json={"title": "X"}).status_code == 428
    stale = {"If-Match": f'"{item["change"] - 1}"'}
    assert logged_in.put(url, json={"title": "X"}, headers=stale).status_code == 412

    response = logged_in.put(
        url,
        json={"title": "Final title", "genre": None},
        headers={"If-Match": etag},
    )
    assert response.status_code == 200
    edited = response.json()
    assert edited["title"] == "Final title"
    assert edited["overrides"] == {"title": "Final title", "genre": None}
    assert response.headers["ETag"] == f'"{edited["change"]}"'

    # The old ETag no longer works: someone else's edit is not overwritten.
    again = logged_in.put(url, json={"title": "Y"}, headers={"If-Match": etag})
    assert again.status_code == 412


def test_overrides_survive_new_versions(
    logged_in: TestClient, doi_registry: FakeDOIRegistry
) -> None:
    doi_registry.records["10.1234/pub"] = {"type": "article-journal", "title": "Pub"}
    item = add(logged_in, "Preprint title")
    edited = logged_in.put(
        f"/api/items/{item['id']}/overrides",
        json={"title": "My title"},
        headers={"If-Match": f'"{item["change"]}"'},
    ).json()
    assert edited["title"] == "My title"
    item = logged_in.post(
        f"/api/items/{item['id']}/versions", json={"doi": "10.1234/pub"}
    ).json()
    assert item["title"] == "My title"
    assert item["type"] == "article-journal"


def test_trash_and_restore_item(logged_in: TestClient) -> None:
    item = add(logged_in, "Old notes")
    assert logged_in.delete(f"/api/items/{item['id']}").status_code == 204
    assert logged_in.get("/api/items").json() == []
    trash = logged_in.get("/api/items", params={"trashed": True}).json()
    assert [i["id"] for i in trash] == [item["id"]]
    assert get(logged_in, item["id"])["deleted_at"] is not None

    response = logged_in.post(
        f"/api/items/{item['id']}/versions", json={"metadata": {"title": "x"}}
    )
    assert response.status_code == 409

    restored = logged_in.post(f"/api/items/{item['id']}/restore").json()
    assert restored["deleted_at"] is None
    assert [i["id"] for i in logged_in.get("/api/items").json()] == [item["id"]]


def test_adding_identifier_of_trashed_item_restores_it(
    logged_in: TestClient, doi_registry: FakeDOIRegistry
) -> None:
    doi_registry.records["10.1234/a"] = {"type": "article-journal", "title": "A"}
    item = logged_in.post("/api/items", json={"doi": "10.1234/a"}).json()
    logged_in.delete(f"/api/items/{item['id']}")
    again = logged_in.post("/api/items", json={"doi": "10.1234/a"})
    assert again.status_code == 200
    assert again.json()["id"] == item["id"]
    assert again.json()["deleted_at"] is None


def test_trash_and_restore_file(logged_in: TestClient) -> None:
    item = add(logged_in, "Paper")
    file = logged_in.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("a.pdf", PDF, "application/pdf")},
    ).json()
    assert logged_in.delete(f"/api/files/{file['id']}").status_code == 204
    [listed] = get(logged_in, item["id"])["versions"][0]["files"]
    assert listed["deleted_at"] is not None
    restored = logged_in.post(f"/api/files/{file['id']}/restore").json()
    assert restored["deleted_at"] is None
