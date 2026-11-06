"""Smart collections: papers found by rules instead of added by hand."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.people import Person, group


def paper(
    person: Person,
    title: str,
    year: int | None = None,
    kind: str = "article-journal",
    tags: tuple[str, ...] = (),
    library: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"title": title, "type": kind}
    if year is not None:
        metadata["issued"] = {"date-parts": [[year]]}
    response = person.post(
        "/api/items", json={"metadata": metadata, "library_id": library}
    )
    assert response.status_code == 201, response.text
    item: dict[str, Any] = response.json()
    for name in tags:
        person.post(f"/api/items/{item['id']}/tags", json={"name": name})
    return item


def smart(person: Person, rules: dict[str, Any], **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    response = person.post(
        "/api/collections", json={"name": "Smart", "rules": rules, **fields}
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def tag_ids(person: Person) -> dict[str, str]:
    return {t["name"]: t["id"] for t in person.get("/api/tags").json()}


def test_rules_find_papers(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    paper(ada, "Radar 2019", 2019, tags=("radar", "read"))
    paper(ada, "Radar 2023", 2023, tags=("radar",))
    paper(ada, "Rain book 2021", 2021, kind="book", tags=("rain",))
    paper(ada, "No year", tags=("radar",))
    tags = tag_ids(ada)

    recent_radar = smart(ada, {"tags_all": [tags["radar"]], "year_from": 2020})
    assert ada.titles(collection=recent_radar["id"]) == ["Radar 2023"]
    assert recent_radar["count"] == 1 and recent_radar["rules"]["year_from"] == 2020

    unread = smart(ada, {"tags_any": [tags["radar"], tags["rain"]],
                         "tags_none": [tags["read"]]})  # fmt: skip
    assert ada.titles(collection=unread["id"]) == [
        "No year",
        "Radar 2023",
        "Rain book 2021",
    ]
    books = smart(ada, {"types": ["book"], "year_to": 2021})
    assert ada.titles(collection=books["id"]) == ["Rain book 2021"]
    new = smart(ada, {"added_days": 7})
    listed = {c["id"]: c for c in ada.get("/api/collections").json()}
    assert listed[new["id"]]["count"] == 4
    assert len(listed[new["id"]]["recent"]) == 3

    # The year follows the paper's details.
    item = paper(ada, "Later", 2018, tags=("radar",))
    etag = ada.get(f"/api/items/{item['id']}").headers["ETag"]
    edited = ada.client.put(
        f"/api/items/{item['id']}/overrides",
        json={"issued": {"date-parts": [[2024]]}},
        headers={**ada.headers, "If-Match": etag},
    )
    assert edited.is_success, edited.text
    assert "Later" in ada.titles(collection=recent_radar["id"])

    # Changing the rules.
    changed = ada.patch(
        f"/api/collections/{books['id']}", {"rules": {"types": ["article-journal"]}}
    ).json()
    assert changed["count"] == 4


def test_smart_collections_hold_nothing_by_hand(
    client: TestClient, db: Session
) -> None:
    ada = Person(client, db, "ada")
    item = paper(ada, "A paper", 2020)
    rules = smart(ada, {"year_from": 2000})
    add = ada.post(f"/api/collections/{rules['id']}/items", {"item_ids": [item["id"]]})
    assert add.status_code == 409
    inside = ada.post("/api/collections", {"name": "In", "parent_id": rules["id"]})
    assert inside.status_code == 409

    # A collection with papers does not become smart; an empty one does.
    folder = ada.post("/api/collections", {"name": "Folder"}).json()
    ada.post(f"/api/collections/{folder['id']}/items", {"item_ids": [item["id"]]})
    refused = ada.patch(f"/api/collections/{folder['id']}", {"rules": {}})
    assert refused.status_code == 409
    empty = ada.post("/api/collections", {"name": "Empty"}).json()
    became = ada.patch(f"/api/collections/{empty['id']}", {"rules": {}}).json()
    assert became["rules"] is not None and became["count"] == 1
    # Kept inside a folder, it adds nothing to the folder.
    ada.patch(f"/api/collections/{rules['id']}", {"parent_id": folder["id"]})
    listed = {c["id"]: c for c in ada.get("/api/collections").json()}
    assert listed[folder["id"]]["count"] == 1
    assert ada.titles(collection=folder["id"]) == ["A paper"]
    back = ada.patch(f"/api/collections/{rules['id']}", {"rules": None}).json()
    assert back["rules"] is None and back["count"] == 0


def test_a_groups_smart_collection_holds_its_papers(
    client: TestClient, db: Session
) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    chair = group(root, "Chair", ada)
    paper(ada, "Mine", 2022)
    paper(ada, "The chair's", 2022, library=chair["library_id"])
    shared = smart(ada, {"year_from": 2020}, library_id=chair["library_id"])
    assert ada.titles(collection=shared["id"]) == ["The chair's"]
    # A person's own one sees all they can read, or the owners chosen.
    mine = smart(ada, {"year_from": 2020})
    assert ada.titles(collection=mine["id"]) == ["Mine", "The chair's"]
    only = smart(ada, {"owners": [chair["library_id"]]})
    assert ada.titles(collection=only["id"]) == ["The chair's"]
