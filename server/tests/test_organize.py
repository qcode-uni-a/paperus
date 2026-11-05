"""Tags and (nested) collections."""

from typing import Any

from fastapi.testclient import TestClient


def add(client: TestClient, title: str) -> dict[str, Any]:
    result: dict[str, Any] = client.post(
        "/api/items", json={"metadata": {"title": title}}
    ).json()
    return result


def tag(client: TestClient, item_id: str, name: str) -> list[dict[str, Any]]:
    response = client.post(f"/api/items/{item_id}/tags", json={"name": name})
    assert response.status_code == 201, response.text
    result: list[dict[str, Any]] = response.json()
    return result


def collection(client: TestClient, name: str, parent: str | None = None) -> str:
    response = client.post("/api/collections", json={"name": name, "parent_id": parent})
    assert response.status_code == 201, response.text
    collection_id: str = response.json()["id"]
    return collection_id


def titles(client: TestClient, **params: str | bool | list[str]) -> list[str]:
    return sorted(i["title"] for i in client.get("/api/items", params=params).json())


def test_tags(logged_in: TestClient) -> None:
    a, b = add(logged_in, "A"), add(logged_in, "B")
    assert [t["name"] for t in tag(logged_in, a["id"], "  To   read ")] == ["To read"]
    # Same tag regardless of case; no duplicates on an item.
    tags = tag(logged_in, b["id"], "to READ")
    assert tags == [{"id": tags[0]["id"], "name": "To read", "source": "manual"}]
    tag(logged_in, b["id"], "to read")
    tag(logged_in, b["id"], "Hydrology")

    listed = {t["name"]: t for t in logged_in.get("/api/tags").json()}
    assert {n: t["count"] for n, t in listed.items()} == {"Hydrology": 1, "To read": 2}
    to_read, hydrology = listed["To read"]["id"], listed["Hydrology"]["id"]

    assert titles(logged_in, tag=to_read) == ["A", "B"]
    assert titles(logged_in, tag=[to_read, hydrology]) == ["B"]
    item = logged_in.get(f"/api/items/{b['id']}").json()
    assert [t["name"] for t in item["tags"]] == ["Hydrology", "To read"]

    remaining = logged_in.delete(f"/api/items/{b['id']}/tags/{hydrology}").json()
    assert [t["name"] for t in remaining] == ["To read"]
    assert (
        logged_in.post(f"/api/items/{a['id']}/tags", json={"name": "  "}).status_code
        == 422
    )


def test_rename_and_delete_tags(logged_in: TestClient) -> None:
    a = add(logged_in, "A")
    [first] = tag(logged_in, a["id"], "methdo")
    tag(logged_in, a["id"], "data")
    renamed = logged_in.patch(f"/api/tags/{first['id']}", json={"name": "Method"})
    assert renamed.json()["name"] == "Method"
    clash = logged_in.patch(f"/api/tags/{first['id']}", json={"name": "DATA"})
    assert clash.status_code == 409
    assert logged_in.delete(f"/api/tags/{first['id']}").status_code == 204
    item = logged_in.get(f"/api/items/{a['id']}").json()
    assert [t["name"] for t in item["tags"]] == ["data"]


def test_nested_collections(logged_in: TestClient) -> None:
    a, b, c = add(logged_in, "A"), add(logged_in, "B"), add(logged_in, "C")
    thesis = collection(logged_in, "Thesis")
    chapter = collection(logged_in, "Chapter 2", parent=thesis)
    logged_in.post(f"/api/collections/{thesis}/items", json={"item_ids": [a["id"]]})
    response = logged_in.post(
        f"/api/collections/{chapter}/items",
        json={
            "item_ids": [
                b["id"],
                c["id"],
                b["id"],
                "00000000-0000-7000-8000-000000000000",
            ]
        },
    )
    assert response.json()["count"] == 2

    assert titles(logged_in, collection=thesis) == ["A", "B", "C"]
    assert titles(logged_in, collection=thesis, nested=False) == ["A"]
    assert titles(logged_in, collection=chapter) == ["B", "C"]
    item = logged_in.get(f"/api/items/{b['id']}").json()
    assert item["collection_ids"] == [chapter]

    listed = {c["name"]: c for c in logged_in.get("/api/collections").json()}
    assert listed["Chapter 2"]["parent_id"] == thesis
    # Items of the collections inside count too, each once.
    assert listed["Thesis"]["count"] == 3
    assert listed["Chapter 2"]["count"] == 2
    logged_in.post(f"/api/collections/{thesis}/items", json={"item_ids": [b["id"]]})
    listed = {c["name"]: c for c in logged_in.get("/api/collections").json()}
    assert listed["Thesis"]["count"] == 3
    assert [p["title"] for p in listed["Thesis"]["recent"]].count("B") == 1
    # B is directly in Thesis and in Chapter 2; the list shows it once.
    assert titles(logged_in, collection=thesis) == ["A", "B", "C"]
    response = logged_in.get("/api/items", params={"collection": thesis})
    assert response.headers["X-Total-Count"] == "3"
    assert titles(logged_in, collection=thesis, nested=False) == ["A", "B"]

    logged_in.delete(f"/api/collections/{chapter}/items/{c['id']}")
    assert titles(logged_in, collection=chapter) == ["B"]


def test_move_collections(logged_in: TestClient) -> None:
    top = collection(logged_in, "Top")
    middle = collection(logged_in, "Middle", parent=top)
    low = collection(logged_in, "Low", parent=middle)
    into_itself = logged_in.patch(f"/api/collections/{top}", json={"parent_id": low})
    assert into_itself.status_code == 409
    moved = logged_in.patch(f"/api/collections/{low}", json={"parent_id": None})
    assert moved.json()["parent_id"] is None
    renamed = logged_in.patch(f"/api/collections/{middle}", json={"name": "Centre"})
    assert (renamed.json()["name"], renamed.json()["parent_id"]) == ("Centre", top)
    missing = "00000000-0000-7000-8000-000000000000"
    assert (
        logged_in.patch(
            f"/api/collections/{low}", json={"parent_id": missing}
        ).status_code
        == 404
    )


def test_deleting_a_collection_keeps_items(logged_in: TestClient) -> None:
    a = add(logged_in, "A")
    top = collection(logged_in, "Top")
    below = collection(logged_in, "Below", parent=top)
    logged_in.post(f"/api/collections/{below}/items", json={"item_ids": [a["id"]]})
    before = logged_in.get(f"/api/items/{a['id']}").json()["change"]
    assert logged_in.delete(f"/api/collections/{top}").status_code == 204
    assert logged_in.get("/api/collections").json() == []
    item = logged_in.get(f"/api/items/{a['id']}").json()
    assert item["collection_ids"] == []
    assert item["change"] > before
    assert titles(logged_in) == ["A"]


def test_tagging_changes_the_item_for_sync(logged_in: TestClient) -> None:
    a = add(logged_in, "A")
    since = int(logged_in.get("/api/items").headers["Last-Change"])
    tag(logged_in, a["id"], "new")
    changed = logged_in.get("/api/items", params={"since": since}).json()
    assert [i["id"] for i in changed] == [a["id"]]


def test_collection_previews(logged_in: TestClient) -> None:
    items = [add(logged_in, f"Paper {n}") for n in range(4)]
    shelf = collection(logged_in, "Shelf")
    for item in items:
        logged_in.post(
            f"/api/collections/{shelf}/items", json={"item_ids": [item["id"]]}
        )
    logged_in.delete(f"/api/items/{items[3]['id']}")
    [listed] = logged_in.get("/api/collections").json()
    assert [p["title"] for p in listed["recent"]] == ["Paper 2", "Paper 1", "Paper 0"]
    assert listed["count"] == 3
