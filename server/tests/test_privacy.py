"""Nothing of a person's private library reaches anyone else: every route
and every assistant tool, tried by another person and by a site
administrator with the ids of the private things."""

import json
import re
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus import authors
from paperus.models import File
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.pdfs import make_pdf
from tests.people import Person, group
from tests.test_mcp import ALL, Assistant, token

SECRET = "zebracorn"
"""In every private thing of Ada's, and what others search for."""
MARKERS = (
    "the zebracorn paper",
    "xenia zebracorn",
    "zebracorn habits",
    "zebracorns",
    "zebracorn-tag",
    "zebracorn shelf",
    "zebracorn thoughts",
)
"""Ada's private texts: no answer to anyone else may hold one."""


def leaked(text: str) -> list[str]:
    return [marker for marker in MARKERS if marker in text.lower()]


def private_library(db: Session, blobs: BlobStore, ada: Person) -> dict[str, str]:
    """Ada's private paper, file, tag, collection, note and author; their ids
    by the name of the path parameter."""
    paper = ada.post(
        "/api/items",
        json={
            "metadata": {
                "title": f"The {SECRET} paper",
                "author": [{"family": "Zebracorn", "given": "Xenia"}],
                "abstract": f"About {SECRET}s.",
            },
            "identifiers": [{"scheme": "doi", "value": "10.5555/zebracorn"}],
        },
    ).json()
    item_id = paper["id"]
    pdf = make_pdf([[f"The {SECRET} paper", f"Passage on {SECRET} habits."]])
    file = ada.post(
        f"/api/items/{item_id}/files",
        files={"upload": ("zebracorn.pdf", pdf, "application/pdf")},
    ).json()
    process_file(db, blobs, uuid.UUID(file["id"]))
    db.commit()
    tag = ada.post(f"/api/items/{item_id}/tags", {"name": f"{SECRET}-tag"}).json()
    collection = ada.post("/api/collections", {"name": f"{SECRET} shelf"}).json()
    ada.post(f"/api/collections/{collection['id']}/items", {"item_ids": [item_id]})
    note = ada.note(f"{SECRET} thoughts", items=[item_id])["id"]
    annotation = ada.post(
        f"/api/files/{file['id']}/annotations",
        {
            "kind": "highlight",
            "page_index": 0,
            "position": {"rects": [[72, 700, 200, 712]]},
            "comment": f"{SECRET} remark",
        },
    ).json()
    authors.link_waiting(db)
    found = ada.get("/api/authors", {"q": "Zebracorn"}).json()
    record = db.get(File, uuid.UUID(file["id"]))
    assert record is not None
    return {
        "item_id": item_id,
        "version_id": paper["versions"][0]["id"],
        "file_id": file["id"],
        "sha256": record.blob_sha256.hex(),
        "tag_id": next(t["id"] for t in tag if t["name"] == f"{SECRET}-tag"),
        "collection_id": collection["id"],
        "note_id": note,
        "annotation_id": annotation["id"],
        "author_id": found[0]["id"],
        "user_id": ada.id,
        "position": "1",
    }


def concrete(path: str, ids: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: ids.get(m.group(1), str(uuid.uuid4())), path)


def test_routes_show_nothing_private(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    ids = private_library(db, blobs, ada)
    assert SECRET in ada.get(f"/api/items/{ids['item_id']}").text
    app = client.app
    assert isinstance(app, FastAPI)
    routes = [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        # Not the live stream: endless, and it says only that something
        # changed (tests/test_sync.py).
        if path.startswith("/api") and path != "/api/changes/live"
        for method in operations
    ]
    query = {"q": SECRET, "doi": "10.5555/zebracorn", "query": SECRET}
    # Ada herself finds them in many places: the check below can fail.
    hers = [
        path
        for method, path in routes
        if method == "GET" and leaked(ada.get(concrete(path, ids), query).text)
    ]
    assert len(hers) >= 10, hers
    for name, person in (("bob", bob), ("root", root)):
        for method, path in routes:
            if method != "GET":
                continue
            response = person.get(concrete(path, ids), query)
            assert not leaked(response.text), (name, path)
    # Changing them: refused (the administrator manages users, not their
    # papers).
    for name, person in (("bob", bob), ("root", root)):
        for method, path in routes:
            names = set(re.findall(r"\{(\w+)\}", path))
            # Only what addresses Ada's things (not one's own hints, tokens).
            if method == "GET" or not names or not names <= set(ids):
                continue
            if person is root and ("{user_id}" in path or "/admin/" in path):
                continue
            response = client.request(
                method,
                concrete(path, ids),
                headers=person.headers,
                json={},
            )
            assert response.status_code >= 400, (name, method, path)
    # All still there.
    item = ada.get(f"/api/items/{ids['item_id']}").json()
    assert item["title"] == f"The {SECRET} paper" and item["tags"]
    assert item["files"] and ada.get(f"/api/notes/{ids['note_id']}").status_code == 200


def arguments(schema: dict[str, Any], ids: dict[str, str]) -> dict[str, Any]:
    """Ada's ids for each id a tool takes; for its other required arguments
    the secret word, or the first value allowed."""
    single = {
        "paper_id": ids["item_id"],
        "keep_id": ids["item_id"],
        "file_id": ids["file_id"],
        "note_id": ids["note_id"],
        "collection_id": ids["collection_id"],
        "author_id": ids["author_id"],
    }
    required = set(schema.get("required", []))
    values: dict[str, Any] = {}
    for name, spec in schema.get("properties", {}).items():
        if name in single:
            values[name] = single[name]
        elif name.endswith("_ids"):
            values[name] = [single.get(name.removesuffix("s"), ids["item_id"])]
        elif name not in required:
            continue
        elif "enum" in spec:
            values[name] = spec["enum"][0]
        elif spec.get("type") == "integer":
            values[name] = 0
        elif spec.get("type") == "array":
            values[name] = [SECRET]
        else:
            values[name] = SECRET
    return values


def test_assistants_see_nothing_private(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    ids = private_library(db, blobs, ada)
    own = Assistant(client, token(ada, *ALL))
    assistant = Assistant(client, token(bob, *ALL))
    client.cookies.clear()
    tools = assistant.rpc("tools/list")["tools"]
    assert len(tools) > 30
    # Ada's own assistant finds them with these arguments.
    found = [
        tool["name"]
        for tool in tools
        if tool.get("annotations", {}).get("readOnlyHint")
        and leaked(
            json.dumps(
                own.rpc(
                    "tools/call",
                    {
                        "name": tool["name"],
                        "arguments": arguments(tool["inputSchema"], ids),
                    },
                )
            )
        )
    ]
    assert len(found) >= 12, found
    for tool in tools:
        result = assistant.rpc(
            "tools/call",
            {"name": tool["name"], "arguments": arguments(tool["inputSchema"], ids)},
        )
        assert not leaked(json.dumps(result)), tool["name"]
    item = ada.get(f"/api/items/{ids['item_id']}").json()
    assert item["title"] == f"The {SECRET} paper" and item["tags"]


def test_others_private_tags_and_collections(
    client: TestClient, db: Session, blobs: BlobStore
) -> None:
    """Filtering by another person's tag or collection is refused, and
    tagging or filing a group paper privately does not move it up in the
    others' recent papers."""
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    ids = private_library(db, blobs, ada)
    for url in (
        f"/api/items?tag={ids['tag_id']}",
        f"/api/items?tag_none={ids['tag_id']}",
        f"/api/items?collection={ids['collection_id']}",
        f"/api/notes?collection={ids['collection_id']}",
    ):
        assert bob.get(url).status_code == 404, url
        assert ada.get(url).status_code == 200, url

    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    library = ada.libraries()["Chair"]["id"]
    first = ada.add("First", library)["id"]
    ada.add("Second", library)
    before = [i["id"] for i in ada.get("/api/items", {"sort": "recent"}).json()]
    bob.post(f"/api/items/{first}/tags", {"name": "reading"})
    shelf = bob.post("/api/collections", {"name": "Mine"}).json()["id"]
    bob.post(f"/api/collections/{shelf}/items", {"item_ids": [first]})
    after = [i["id"] for i in ada.get("/api/items", {"sort": "recent"}).json()]
    assert after == before
