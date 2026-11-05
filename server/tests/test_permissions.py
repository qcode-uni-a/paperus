"""The permission matrix of docs/permissions.md, row by row.

Each test is one row of a table there (its name says which); it checks
every column. People: ``me`` owns things, ``reader``/``member`` are in the
group "Chair" with that role, ``admin`` is the Chair's admin, ``outsider``
is in no group and ``root`` is a site administrator in no group.
"""

from dataclasses import dataclass
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import FakeDOIRegistry
from tests.people import Person, group

PDF = b"%PDF-1.7\n" + b"x" * 3000 + b"\n%%EOF\n"


@dataclass
class World:
    root: Person
    admin: Person
    member: Person
    reader: Person
    outsider: Person
    chair: dict[str, Any]
    lab: dict[str, Any]
    """Another group, where ``member`` is a member too."""

    @property
    def library(self) -> str:
        library: str = self.chair["library_id"]
        return library

    def paper(self, title: str = "Group paper") -> dict[str, Any]:
        """A paper the Chair owns."""
        return self.admin.add(title, self.library)


@pytest.fixture
def w(client: TestClient, db: Session) -> World:
    root = Person(client, db, "root", admin=True)
    admin, member, reader, outsider = (
        Person(client, db, name) for name in ("admin", "member", "reader", "outsider")
    )
    chair = group(root, "Chair", admin)
    lab = group(root, "Lab", admin)
    for person, role in ((member, "member"), (reader, "reader")):
        admin.put(f"/api/groups/{chair['id']}/members/{person.id}", json={"role": role})
    admin.put(f"/api/groups/{lab['id']}/members/{member.id}", json={"role": "member"})
    return World(root, admin, member, reader, outsider, chair, lab)


def own(person: Person) -> str:
    library: str = person.libraries()["Me"]["id"]
    return library


def etag(person: Person, item_id: str) -> str:
    return person.get(f"/api/items/{item_id}").headers["ETag"]


# Papers


def test_papers_see_search_open_files(w: World) -> None:
    mine = w.reader.add("Reader's own")
    shared = w.paper()
    file = w.admin.post(
        f"/api/items/{shared['id']}/files",
        files={"upload": ("p.pdf", PDF, "application/pdf")},
    ).json()
    assert w.reader.get(f"/api/items/{mine['id']}").status_code == 200  # mine
    for person in (w.reader, w.member):  # group's, as reader and as member
        assert person.get(f"/api/items/{shared['id']}").status_code == 200
        assert "Group paper" in person.titles()
        assert person.get(f"/api/files/{file['id']}/content").status_code == 200
    for person in (w.outsider, w.root):  # neither sees anything
        assert person.get(f"/api/items/{shared['id']}").status_code == 404
        assert person.get(f"/api/files/{file['id']}/content").status_code == 404
        assert person.titles() == []


def change_details(person: Person, item_id: str) -> list[int]:
    """Overrides, a new version and a new file: their status codes."""
    overrides = person.client.put(
        f"/api/items/{item_id}/overrides",
        headers={**person.headers, "If-Match": etag(person, item_id)},
        json={"title": "Changed"},
    )
    version = person.post(
        f"/api/items/{item_id}/versions",
        json={"metadata": {"title": "Preprint"}, "kind": "preprint"},
    )
    file = person.post(
        f"/api/items/{item_id}/files",
        files={"upload": ("p.pdf", PDF, "application/pdf")},
    )
    return [overrides.status_code, version.status_code, file.status_code]


def test_papers_change_details_versions_files(w: World) -> None:
    assert change_details(w.reader, w.reader.add("Mine")["id"]) == [200, 201, 201]
    assert change_details(w.reader, w.paper()["id"]) == [403, 403, 403]
    assert change_details(w.member, w.paper()["id"]) == [200, 201, 201]


def test_papers_trash_and_restore(w: World) -> None:
    for person, item, expected in (
        (w.reader, w.reader.add("Mine"), (204, 200)),
        (w.reader, w.paper(), (403, 403)),
        (w.member, w.paper(), (204, 200)),
    ):
        trashed = person.delete(f"/api/items/{item['id']}").status_code
        if trashed != 204:
            w.admin.delete(f"/api/items/{item['id']}")  # to try restoring
        restored = person.post(f"/api/items/{item['id']}/restore").status_code
        assert (trashed, restored) == expected


def test_papers_give_to_a_group(w: World) -> None:
    # Mine, to a group I may add to (not one I only read).
    mine = w.member.add("Mine")
    assert (
        w.member.put(
            f"/api/items/{mine['id']}/owner", json={"library_id": w.library}
        ).json()["library_id"]
        == w.library
    )
    theirs = w.reader.add("Reader's")
    assert (
        w.reader.put(
            f"/api/items/{theirs['id']}/owner", json={"library_id": w.library}
        ).status_code
        == 403
    )
    # A group's: readers cannot, members can (to another group they are in).
    shared = w.paper()
    assert (
        w.reader.put(
            f"/api/items/{shared['id']}/owner", json={"library_id": w.lab["library_id"]}
        ).status_code
        == 403
    )
    moved = w.member.put(
        f"/api/items/{shared['id']}/owner", json={"library_id": w.lab["library_id"]}
    )
    assert moved.json()["library_id"] == w.lab["library_id"]


def test_papers_take_for_myself(w: World) -> None:
    shared = w.paper()
    assert (
        w.reader.put(
            f"/api/items/{shared['id']}/owner", json={"library_id": own(w.reader)}
        ).status_code
        == 403
    )
    taken = w.member.put(
        f"/api/items/{shared['id']}/owner", json={"library_id": own(w.member)}
    )
    assert taken.json()["library_id"] == own(w.member)
    assert "Group paper" not in w.reader.titles()


def test_papers_owner_change_keeps_tags_lets_group_collections_go(w: World) -> None:
    shared = w.paper()
    w.member.post(f"/api/items/{shared['id']}/tags", json={"name": "method"})
    folder = w.member.post(
        "/api/collections", json={"name": "Folder", "library_id": w.library}
    ).json()
    w.member.post(
        f"/api/collections/{folder['id']}/items", json={"item_ids": [shared["id"]]}
    )
    taken = w.member.put(
        f"/api/items/{shared['id']}/owner", json={"library_id": own(w.member)}
    ).json()
    assert [t["name"] for t in taken["tags"]] == ["method"]
    assert taken["collection_ids"] == []


def test_papers_default_owner_and_known_papers(w: World) -> None:
    assert w.member.add("Default")["library_id"] == own(w.member)
    w.member.put("/api/me/default-library", json={"library_id": w.library})
    paper = w.member.add("Into the group")
    assert paper["library_id"] == w.library
    # A file one can already see is found, not added again; others' private
    # files stay invisible, so they get their own item.
    upload = w.member.post(
        "/api/uploads", files={"upload": ("a.pdf", PDF, "application/pdf")}
    ).json()
    again = w.reader.post(
        "/api/uploads", files={"upload": ("b.pdf", PDF, "application/pdf")}
    ).json()
    assert (again["existing"], again["item_id"]) == (True, upload["item_id"])
    other = w.outsider.post(
        "/api/uploads", files={"upload": ("c.pdf", PDF, "application/pdf")}
    ).json()
    assert other["existing"] is False


def test_papers_merge(w: World, doi_registry: FakeDOIRegistry) -> None:
    doi_registry.records["10.1234/x"] = {"type": "journal-article", "title": "X"}
    doi_registry.records["10.48550/arxiv.2101.00001"] = {
        "type": "article",
        "title": "X",
    }
    # The member's private copy and the group's paper (another version).
    group_paper = w.admin.post(
        "/api/items", json={"doi": "10.1234/x", "library_id": w.library}
    ).json()
    mine = w.member.post(
        "/api/items", json={"doi": "10.48550/arxiv.2101.00001", "kind": "preprint"}
    ).json()
    w.member.post(
        f"/api/items/{mine['id']}/files",
        files={"upload": ("annotated.pdf", PDF, "application/pdf")},
    )
    w.member.post(f"/api/items/{mine['id']}/tags", json={"name": "to read"})
    shelf = make_collection(w.member, "Shelf").json()
    w.member.post(
        f"/api/collections/{shelf['id']}/items", json={"item_ids": [mine["id"]]}
    )
    # Readers cannot merge a group's paper away.
    assert w.reader.post(
        f"/api/items/{group_paper['id']}/merge", json={"into": mine["id"]}
    ).status_code in (403, 404)
    # As member: everything moves; the private tag stays private.
    merged = w.member.post(
        f"/api/items/{mine['id']}/merge", json={"into": group_paper["id"]}
    ).json()
    assert (merged["versions"], merged["tags"], merged["collections"]) == (1, 1, 1)
    assert merged["left_behind"] == []
    assert len(merged["item"]["versions"]) == 2
    assert w.member.get(f"/api/items/{mine['id']}").json()["deleted_at"] is not None
    assert w.admin.get(f"/api/items/{group_paper['id']}").json()["tags"] == []
    assert w.member.titles(collection=shelf["id"]) == ["X"]
    # As reader of the target: only private things move.
    copy = w.reader.add("Reader's copy")
    w.reader.post(f"/api/items/{copy['id']}/tags", json={"name": "mine"})
    result = w.reader.post(
        f"/api/items/{copy['id']}/merge", json={"into": group_paper["id"]}
    ).json()
    assert result["tags"] == 1
    assert result["versions"] == 0
    assert result["left_behind"] == [
        "versions and files (you may not change the other paper)"
    ]
    assert (
        w.member.post(
            f"/api/items/{group_paper['id']}/merge", json={"into": group_paper["id"]}
        ).status_code
        == 409
    )


def test_papers_likely_duplicates(w: World) -> None:
    first = w.member.post(
        "/api/uploads", files={"upload": ("a.pdf", PDF, "application/pdf")}
    ).json()
    # The outsider's copy is invisible to the member, so not a candidate.
    w.outsider.post("/api/uploads", files={"upload": ("b.pdf", PDF, "application/pdf")})
    shared = w.paper("Same file, group")
    w.admin.post(
        f"/api/items/{shared['id']}/files",
        files={"upload": ("c.pdf", PDF, "application/pdf")},
    )
    found = w.member.get(f"/api/items/{first['item_id']}/duplicates").json()
    assert [i["id"] for i in found] == [shared["id"]]


# Tags


def make_tag(person: Person, name: str, library: str | None = None) -> httpx2.Response:
    return person.post("/api/tags", json={"name": name, "library_id": library})


def test_tags_see(w: World) -> None:
    make_tag(w.admin, "group tag", w.library)
    make_tag(w.reader, "reader's tag")
    assert [t["name"] for t in w.reader.get("/api/tags").json()] == [
        "group tag",
        "reader's tag",
    ]
    assert [t["name"] for t in w.member.get("/api/tags").json()] == ["group tag"]
    assert w.outsider.get("/api/tags").json() == []


def test_tags_create(w: World) -> None:
    assert make_tag(w.reader, "mine").status_code == 201
    assert make_tag(w.reader, "group's", w.library).status_code == 403
    assert make_tag(w.member, "group's", w.library).status_code == 201


def test_tags_rename_recolour_describe_delete(w: World) -> None:
    mine = make_tag(w.reader, "mine").json()
    shared = make_tag(w.admin, "shared", w.library).json()
    change = {"name": "renamed", "color": "teal", "description": "Why."}
    assert w.reader.patch(f"/api/tags/{mine['id']}", json=change).status_code == 200
    assert w.reader.delete(f"/api/tags/{mine['id']}").status_code == 204
    assert w.reader.patch(f"/api/tags/{shared['id']}", json=change).status_code == 403
    assert w.reader.delete(f"/api/tags/{shared['id']}").status_code == 403
    assert w.member.patch(f"/api/tags/{shared['id']}", json=change).status_code == 200
    assert w.member.delete(f"/api/tags/{shared['id']}").status_code == 204


def test_tags_give_to_another_owner(w: World) -> None:
    # Mine: to a group I may add to, not to one I only read.
    mine = make_tag(w.member, "mine").json()
    assert (
        w.member.patch(
            f"/api/tags/{mine['id']}", json={"library_id": w.library}
        ).json()["library_id"]
        == w.library
    )
    readers = make_tag(w.reader, "reader's").json()
    assert (
        w.reader.patch(
            f"/api/tags/{readers['id']}", json={"library_id": w.library}
        ).status_code
        == 403
    )
    # A group's: readers cannot; members can, to themselves or another group.
    shared = make_tag(w.admin, "shared", w.library).json()
    assert (
        w.reader.patch(
            f"/api/tags/{shared['id']}", json={"library_id": own(w.reader)}
        ).status_code
        == 403
    )
    lab = w.member.patch(
        f"/api/tags/{shared['id']}", json={"library_id": w.lab["library_id"]}
    )
    assert lab.json()["library_id"] == w.lab["library_id"]
    back = w.member.patch(
        f"/api/tags/{shared['id']}", json={"library_id": own(w.member)}
    )
    assert back.json()["library_id"] == own(w.member)


def tag_on(person: Person, item: dict[str, Any], tag: dict[str, Any]) -> int:
    response = person.post(
        f"/api/items/{item['id']}/tags",
        json={"name": tag["name"], "library_id": tag["library_id"]},
    )
    return response.status_code


def tag_off(person: Person, item: dict[str, Any], tag: dict[str, Any]) -> int:
    return person.delete(f"/api/items/{item['id']}/tags/{tag['id']}").status_code


def test_tags_on_a_paper_of_mine(w: World) -> None:
    shared = make_tag(w.admin, "shared", w.library).json()
    for person in (w.reader, w.member):  # my tag; a group's as reader / member
        paper = person.add("Mine")
        mine = make_tag(person, "mine").json()
        for tag in (mine, shared):
            assert tag_on(person, paper, tag) == 201
            assert tag_off(person, paper, tag) == 200


def test_tags_on_a_groups_paper_as_reader(w: World) -> None:
    paper = w.paper()
    mine = make_tag(w.reader, "mine").json()
    shared = make_tag(w.admin, "shared", w.library).json()
    assert tag_on(w.reader, paper, mine) == 201  # my tag: only I see it
    assert w.admin.get(f"/api/items/{paper['id']}").json()["tags"] == []
    assert tag_off(w.reader, paper, mine) == 200
    assert tag_on(w.reader, paper, shared) == 403
    tag_on(w.admin, paper, shared)
    assert tag_off(w.reader, paper, shared) == 403


def test_tags_on_a_groups_paper_as_member(w: World) -> None:
    paper = w.paper()
    mine = make_tag(w.member, "mine").json()
    shared = make_tag(w.admin, "shared", w.library).json()
    for tag in (mine, shared):
        assert tag_on(w.member, paper, tag) == 201
        assert tag_off(w.member, paper, tag) == 200


def test_tags_group_tag_on_private_paper_is_seen_per_viewer(w: World) -> None:
    shared = make_tag(w.admin, "shared", w.library).json()
    tag_on(w.admin, w.paper(), shared)
    tag_on(w.reader, w.reader.add("Reader's own"), shared)
    counts = {
        person: next(
            t for t in person.get("/api/tags").json() if t["id"] == shared["id"]
        )["count"]
        for person in (w.admin, w.reader)
    }
    assert counts == {w.admin: 1, w.reader: 2}


def test_tags_giving_away_keeps_every_paper(w: World) -> None:
    mine = make_tag(w.member, "mine").json()
    private = w.member.add("Private")
    tag_on(w.member, private, mine)
    w.member.patch(f"/api/tags/{mine['id']}", json={"library_id": w.library})
    tags = w.member.get(f"/api/items/{private['id']}").json()["tags"]
    assert [t["name"] for t in tags] == ["mine"]


# Collections


def make_collection(
    person: Person, name: str, library: str | None = None
) -> httpx2.Response:
    return person.post("/api/collections", json={"name": name, "library_id": library})


def test_collections_see(w: World) -> None:
    make_collection(w.admin, "Group's", w.library)
    make_collection(w.reader, "Reader's")
    assert sorted(c["name"] for c in w.reader.get("/api/collections").json()) == [
        "Group's",
        "Reader's",
    ]
    assert [c["name"] for c in w.member.get("/api/collections").json()] == ["Group's"]
    assert w.outsider.get("/api/collections").json() == []


def test_collections_create_rename_nest_delete(w: World) -> None:
    for person, library, allowed in (
        (w.reader, None, True),
        (w.reader, w.library, False),
        (w.member, w.library, True),
    ):
        created = make_collection(person, "New", library)
        assert created.status_code == (201 if allowed else 403)
        target = (
            created.json()
            if allowed
            else make_collection(w.admin, "Admin's", library).json()
        )
        parent = (
            make_collection(person, "Parent", library).json()
            if allowed
            else make_collection(w.admin, "Parent", library).json()
        )
        codes = [
            person.patch(
                f"/api/collections/{target['id']}",
                json={"name": "Renamed", "description": "Why."},
            ).status_code,
            person.patch(
                f"/api/collections/{target['id']}", json={"parent_id": parent["id"]}
            ).status_code,
            person.delete(f"/api/collections/{target['id']}").status_code,
        ]
        assert codes == ([200, 200, 204] if allowed else [403, 403, 403])


def test_collections_give_to_another_owner(w: World) -> None:
    mine = make_collection(w.member, "Mine").json()
    given = w.member.patch(
        f"/api/collections/{mine['id']}", json={"library_id": w.library}
    )
    assert given.json()["library_id"] == w.library
    readers = make_collection(w.reader, "Reader's").json()
    assert (
        w.reader.patch(
            f"/api/collections/{readers['id']}", json={"library_id": w.library}
        ).status_code
        == 403
    )
    shared = make_collection(w.admin, "Group's", w.library).json()
    assert (
        w.reader.patch(
            f"/api/collections/{shared['id']}", json={"library_id": own(w.reader)}
        ).status_code
        == 403
    )
    taken = w.member.patch(
        f"/api/collections/{shared['id']}", json={"library_id": own(w.member)}
    )
    assert taken.json()["library_id"] == own(w.member)


def test_collections_add_and_remove_papers(w: World) -> None:
    # Mine.
    folder = make_collection(w.reader, "Mine").json()
    paper = w.paper()
    url = f"/api/collections/{folder['id']}/items"
    assert w.reader.post(url, json={"item_ids": [paper["id"]]}).status_code == 200
    assert w.reader.delete(f"{url}/{paper['id']}").status_code == 200
    # A group's: readers cannot, members can.
    shared = make_collection(w.admin, "Group's", w.library).json()
    url = f"/api/collections/{shared['id']}/items"
    assert w.reader.post(url, json={"item_ids": [paper["id"]]}).status_code == 403
    assert w.member.post(url, json={"item_ids": [paper["id"]]}).status_code == 200
    assert w.reader.delete(f"{url}/{paper['id']}").status_code == 403
    assert w.member.delete(f"{url}/{paper['id']}").status_code == 200


def test_collections_what_they_may_hold(w: World) -> None:
    group_paper, private = w.paper(), w.member.add("Member's private")
    mine = make_collection(w.member, "Mine").json()
    shared = make_collection(w.member, "Group's", w.library).json()
    ids = {"item_ids": [group_paper["id"], private["id"]]}
    assert (
        w.member.post(f"/api/collections/{mine['id']}/items", json=ids).json()["count"]
        == 2
    )
    assert (
        w.member.post(f"/api/collections/{shared['id']}/items", json=ids).json()[
            "count"
        ]
        == 1
    )


def test_collections_nest_only_within_one_owner(w: World) -> None:
    mine = make_collection(w.member, "Mine").json()
    response = w.member.post(
        "/api/collections",
        json={"name": "Inside", "parent_id": mine["id"], "library_id": w.library},
    )
    assert response.status_code == 409
    shared = make_collection(w.member, "Group's", w.library).json()
    assert (
        w.member.patch(
            f"/api/collections/{shared['id']}", json={"parent_id": mine["id"]}
        ).status_code
        == 409
    )


def test_collections_given_to_a_group_ask_about_papers(w: World) -> None:
    private = w.member.add("Member's private")
    for add_papers, count in ((False, 0), (True, 1)):
        folder = make_collection(w.member, f"Folder {add_papers}").json()
        w.member.post(
            f"/api/collections/{folder['id']}/items", json={"item_ids": [private["id"]]}
        )
        preview = w.member.get(
            f"/api/collections/{folder['id']}/move-preview",
            params={"library": w.library},
        ).json()
        assert preview == {"papers": 1, "not_in_library": 1}
        moved = w.member.patch(
            f"/api/collections/{folder['id']}",
            json={"library_id": w.library, "add_papers": add_papers},
        ).json()
        assert moved["count"] == count


def test_collections_given_to_me_keep_papers_where_they_are(w: World) -> None:
    paper = w.paper()
    shared = make_collection(w.member, "Group's", w.library).json()
    w.member.post(
        f"/api/collections/{shared['id']}/items", json={"item_ids": [paper["id"]]}
    )
    taken = w.member.patch(
        f"/api/collections/{shared['id']}", json={"library_id": own(w.member)}
    ).json()
    assert taken["count"] == 1
    assert w.member.get(f"/api/items/{paper['id']}").json()["library_id"] == w.library


# Groups


def test_groups_see_the_group_and_its_members(w: World) -> None:
    url = f"/api/groups/{w.chair['id']}/members"
    assert w.outsider.get(url).status_code == 404
    for person in (w.reader, w.member, w.admin, w.root):
        assert person.get(url).status_code == 200


def test_groups_create_a_top_level_group(w: World) -> None:
    for person in (w.outsider, w.reader, w.member, w.admin):
        assert person.post("/api/groups", json={"name": "Mine"}).status_code == 403
    assert w.root.post("/api/groups", json={"name": "Faculty"}).status_code == 201


def test_groups_create_a_group_inside(w: World) -> None:
    body = {"name": "Project", "parent_id": w.chair["id"]}
    assert w.outsider.post("/api/groups", json=body).status_code == 404
    for person in (w.reader, w.member):
        assert person.post("/api/groups", json=body).status_code == 403
    for person in (w.admin, w.root):
        assert person.post("/api/groups", json=body).status_code == 201


def test_groups_rename_and_describe(w: World) -> None:
    url, body = (
        f"/api/groups/{w.chair['id']}",
        {"name": "Chair", "description": "Ours."},
    )
    assert w.outsider.patch(url, json=body).status_code == 404
    for person in (w.reader, w.member):
        assert person.patch(url, json=body).status_code == 403
    for person in (w.admin, w.root):
        assert person.patch(url, json=body).status_code == 200


def test_groups_delete_only_empty(w: World) -> None:
    def project() -> str:
        response = w.admin.post(
            "/api/groups", json={"name": "Project", "parent_id": w.chair["id"]}
        )
        group_id: str = response.json()["id"]
        return group_id

    first = project()
    assert w.outsider.delete(f"/api/groups/{first}").status_code == 404
    for person in (w.reader, w.member):
        assert person.delete(f"/api/groups/{first}").status_code == 403
    assert w.admin.delete(f"/api/groups/{first}").status_code == 204
    assert w.root.delete(f"/api/groups/{project()}").status_code == 204
    w.paper()  # the Chair is not empty
    assert w.admin.delete(f"/api/groups/{w.chair['id']}").status_code == 409


def test_groups_add_change_remove_people(w: World) -> None:
    url = f"/api/groups/{w.chair['id']}/members/{w.outsider.id}"
    assert w.outsider.put(url, json={"role": "admin"}).status_code == 404
    for person in (w.reader, w.member):
        assert person.put(url, json={"role": "reader"}).status_code == 403
        assert person.delete(url).status_code in (403, 404)
    for person in (w.admin, w.root):
        assert person.put(url, json={"role": "reader"}).status_code == 200
        assert person.put(url, json={"role": "member"}).status_code == 200
        assert person.delete(url).status_code == 200


def test_groups_look_up_users(w: World) -> None:
    for person in (w.outsider, w.reader, w.member):
        assert person.get("/api/users").status_code == 403
    for person in (w.admin, w.root):
        assert person.get("/api/users").status_code == 200


def test_groups_keep_an_admin(w: World) -> None:
    url = f"/api/groups/{w.chair['id']}/members/{w.admin.id}"
    assert w.admin.delete(url).status_code == 409
    assert w.admin.put(url, json={"role": "member"}).status_code == 409


def test_groups_leave(w: World) -> None:
    # Direct members leave; who is in through a group above leaves there.
    project = w.admin.post(
        "/api/groups", json={"name": "Project", "parent_id": w.chair["id"]}
    ).json()
    w.admin.put(
        f"/api/groups/{project['id']}/members/{w.outsider.id}", json={"role": "reader"}
    )
    assert w.outsider.post(f"/api/groups/{project['id']}/leave").status_code == 204
    assert w.outsider.get("/api/groups").json() == []
    inherited = w.reader.post(f"/api/groups/{project['id']}/leave")
    assert inherited.status_code == 409
    assert "Chair" in inherited.json()["detail"]
    assert w.reader.post(f"/api/groups/{w.chair['id']}/leave").status_code == 204
    assert w.reader.titles() == []
    # The last admin of a top-level group stays.
    assert w.admin.post(f"/api/groups/{w.chair['id']}/leave").status_code == 409


def test_groups_move(w: World) -> None:
    project = w.admin.post(
        "/api/groups", json={"name": "Project", "parent_id": w.chair["id"]}
    ).json()
    url = f"/api/groups/{project['id']}"
    # Into another group: admins of both (the admin is also the Lab's admin).
    for person in (w.outsider, w.reader, w.member):
        assert person.patch(url, json={"parent_id": w.lab["id"]}).status_code in (
            403,
            404,
        )
    moved = w.admin.patch(url, json={"parent_id": w.lab["id"]})
    assert moved.json()["parent_id"] == w.lab["id"]
    # Never into itself or a group inside it.
    inner = w.admin.post(
        "/api/groups", json={"name": "Inner", "parent_id": project["id"]}
    )
    assert w.admin.patch(url, json={"parent_id": inner.json()["id"]}).status_code == 409
    # To the top: site administrators only.
    assert w.admin.patch(url, json={"parent_id": None}).status_code == 403
    assert w.root.patch(url, json={"parent_id": None}).json()["parent_id"] is None


# Users (site administrators)


def test_users_list_and_create(w: World) -> None:
    for person in (w.outsider, w.member, w.admin):
        assert person.get("/api/admin/users").status_code == 403
        new = {"username": "new", "password": "long enough"}
        assert person.post("/api/admin/users", json=new).status_code == 403
    listed = {u["username"]: u for u in w.root.get("/api/admin/users").json()}
    assert listed["member"]["groups"] == 2
    created = w.root.post(
        "/api/admin/users", json={"username": "new", "password": "long enough"}
    )
    assert created.status_code == 201
    again = w.root.post(
        "/api/admin/users", json={"username": "new", "password": "long enough"}
    )
    assert again.status_code == 409
    login = w.root.client.post(
        "/api/auth/login", json={"username": "new", "password": "long enough"}
    )
    assert login.status_code == 200


def test_users_reset_password_admin_rights_deactivate(w: World) -> None:
    url = f"/api/admin/users/{w.member.id}"
    for person in (w.outsider, w.admin):
        assert person.patch(url, json={"is_admin": True}).status_code == 403
    # A new password logs the person out everywhere.
    assert w.root.patch(url, json={"password": "a new one!"}).status_code == 200
    assert w.member.get("/api/auth/me").status_code == 401
    # Admin rights, but never losing the last administrator.
    assert w.root.patch(url, json={"is_admin": True}).json()["is_admin"] is True
    assert w.root.patch(url, json={"is_admin": False}).json()["is_admin"] is False
    root_url = f"/api/admin/users/{w.root.id}"
    assert w.root.patch(root_url, json={"is_admin": False}).status_code == 409
    assert w.root.patch(root_url, json={"active": False}).status_code == 409
    # Deactivated: no login, sessions end; papers and groups stay.
    reader_url = f"/api/admin/users/{w.reader.id}"
    deactivated = w.root.patch(reader_url, json={"active": False}).json()
    assert deactivated["deactivated_at"] is not None
    assert deactivated["groups"] == 1
    assert w.reader.get("/api/auth/me").status_code == 401
    login = w.root.client.post(
        "/api/auth/login", json={"username": "reader", "password": "secret"}
    )
    assert login.status_code == 401
    assert (
        w.root.patch(reader_url, json={"active": True}).json()["deactivated_at"] is None
    )
