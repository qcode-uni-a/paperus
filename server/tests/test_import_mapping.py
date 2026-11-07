"""Where an imported paperus export's owners, tags and collections go: the
cases of docs/import-mapping.md, section 5 (O1 to O8, T1 to T9, R1, N1)."""

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from paperus import library, organize
from paperus.config import Settings
from paperus.identifiers import Scheme
from paperus.importing.names import likeness
from paperus.models import (
    Collection,
    CollectionItem,
    Group,
    Item,
    ItemTag,
    Library,
    Membership,
    MetadataSource,
    Note,
    Tag,
    TagSource,
    VersionKind,
)
from paperus.storage import BlobStore
from tests.export_library import empty_database, exported, run_imports, upload_export
from tests.people import Person, group

# N1: names (section 3).
PAIRS = [
    ("Thesis", "thesis", "same"),
    ("ToRead", "to read", "nearly"),
    ("Quantum_Dots", "Quantum dots", "nearly"),
    ("Thesis", "Theses", "nearly"),
    ("Mónica", "Monica", "nearly"),
    ("Notes", "Note", "nearly"),
    ("Studies", "Study", "nearly"),
    ("Thesis", "PhD/Thesis", "similar"),
    ("Floquet", "Floquet systems", "similar"),
    ("Floquet sytems", "Floquet systems", "similar"),
    ("ML", "Machine learning", None),
    ("Optics", "Topics", None),
    ("Qubits", "Quantum", None),
    ("Uni", "Uni/QCode Lab", None),
]


@pytest.mark.parametrize(("a", "b", "expected"), PAIRS)
def test_n1_names(a: str, b: str, expected: str | None) -> None:
    assert likeness(a, b) == expected
    assert likeness(b, a) == expected


# An export to import: ada's papers (and her group's, where asked).


def _library_of(db: Session, person: Person) -> uuid.UUID:
    return db.scalars(
        select(Library.id).where(Library.user_id == uuid.UUID(person.id))
    ).one()


def _paper(
    db: Session, owner: uuid.UUID, title: str, doi: str, user: str | None = None
) -> Item:
    return library.create_item(
        db,
        owner,
        kind=VersionKind.PUBLISHED,
        label=None,
        csl={"type": "article-journal", "title": title},
        source=MetadataSource.MANUAL,
        identifiers=[(Scheme.DOI, doi)],
        added_by=uuid.UUID(user) if user else None,
    )


def _collection(
    db: Session,
    owner: uuid.UUID,
    name: str,
    parent: Collection | None = None,
    rules: dict[str, Any] | None = None,
) -> Collection:
    collection = Collection(
        library_id=owner,
        name=name,
        parent_id=parent.id if parent else None,
        rules=rules,
        change=0,
    )
    db.add(collection)
    db.flush()
    return collection


Export = Callable[..., list[Path]]


@pytest.fixture
def export_of(
    client: TestClient,
    db: Session,
    job_app: App,
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    tmp_path: Path,
) -> Export:
    """``export_of(groups=…)``: ada's library exported (groups: paths of
    groups she is a member of, each with a paper and a collection), then
    the server emptied; the zips."""

    def make(groups: tuple[str, ...] = ()) -> list[Path]:
        root = Person(client, db, "root", admin=True)
        ada = Person(client, db, "ada")
        mine = _library_of(db, ada)
        parent = None
        for path in groups:
            created = group(root, path.rsplit("/", 1)[-1], root, parent=parent)
            parent = created["id"]
            response = root.put(
                f"/api/groups/{created['id']}/members/{ada.id}", {"role": "member"}
            )
            assert response.status_code in (200, 204)
            lab = uuid.UUID(created["library_id"])
            paper = _paper(db, lab, f"Paper of {path}", f"10.1/{len(path)}", root.id)
            reading = _collection(db, lab, "Reading")
            organize.add_to_collection(db, reading, [paper.id], None)
        radar = _paper(db, mine, "Radar gaps", "10.1/radar", ada.id)
        other = _paper(db, mine, "Rain", "10.1/rain", ada.id)
        user = uuid.UUID(ada.id)
        organize.tag_item(db, radar, "to read", library_id=mine, user_id=user)
        topics = organize.tag_item(db, radar, "Topics", library_id=mine, user_id=user)
        organize.tag_item(
            db,
            radar,
            "Quantum Physics",
            library_id=mine,
            source=TagSource.AUTOMATIC,
        )
        thesis = _collection(db, mine, "Thesis")
        chapter = _collection(db, mine, "Chapter 1", thesis)
        organize.add_to_collection(db, thesis, [other.id], user)
        organize.add_to_collection(db, chapter, [radar.id], user)
        _collection(db, mine, "Physics", rules={"tags_any": [str(topics.id)]})
        db.commit()
        parts = exported(
            ada, job_app, engine, blobs, settings, tmp_path / f"e{len(groups)}"
        )
        db.rollback()
        empty_database(engine)
        db.expire_all()
        return parts

    return make


def upload(person: Person, parts: list[Path]) -> dict[str, Any]:
    response = upload_export(person, parts)
    assert response.status_code == 201, response.text
    record: dict[str, Any] = response.json()
    assert record["status"] == "needs_choices"
    return record


def preview(person: Person, record: dict[str, Any], **body: Any) -> dict[str, Any]:  # noqa: ANN401
    response = person.post(f"/api/imports/{record['id']}/preview", json=body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def start(person: Person, record: dict[str, Any], **body: Any) -> Any:  # noqa: ANN401
    return person.post(f"/api/imports/{record['id']}/start", json=body)


def done(
    person: Person, db: Session, blobs: BlobStore, job_app: App, record: dict[str, Any]
) -> dict[str, Any]:
    run_imports(db, blobs, job_app)
    result: dict[str, Any] = person.get(f"/api/imports/{record['id']}").json()
    assert result["status"] == "done", result
    db.expire_all()
    return result


def owner_named(record: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(
        o for o in record["choices"]["owners"] if o["name"] == name
    )
    return found


def collection(db: Session, owner: uuid.UUID, path: str) -> Collection:
    parent: uuid.UUID | None = None
    found: Collection | None = None
    for name in path.split("/"):
        place = (
            Collection.parent_id == parent if parent else Collection.parent_id.is_(None)
        )
        found = db.scalars(
            select(Collection).where(
                Collection.library_id == owner, Collection.name == name, place
            )
        ).one()
        parent = found.id
    assert found is not None
    return found


def titles_in(db: Session, collection_id: uuid.UUID) -> list[str]:
    return sorted(
        db.scalars(
            select(Item.title)
            .join(CollectionItem, CollectionItem.item_id == Item.id)
            .where(CollectionItem.collection_id == collection_id)
        )
    )


def counts(db: Session) -> dict[str, int]:
    return {
        model.__tablename__: db.scalar(select(func.count()).select_from(model)) or 0
        for model in (Item, Tag, ItemTag, Collection, CollectionItem, Note, Group)
    }


# Owners


def test_o1_me_only_on_an_empty_server(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    parts = export_of()
    carol = Person(client, db, "carol")
    record = upload(carol, parts)
    assert [o["name"] for o in record["choices"]["owners"]] == ["Me"]
    assert preview(carol, record) == {"tags": [], "collections": [], "targets": {}}
    assert start(carol, record).status_code == 200
    report = done(carol, db, blobs, job_app, record)["report"]
    assert report["added"] == 2 and report["problems"] == []
    mine = _library_of(db, carol)
    assert {i.library_id for i in db.scalars(select(Item))} == {mine}
    assert titles_in(db, collection(db, mine, "Thesis/Chapter 1").id) == ["Radar gaps"]


def test_o2_a_group_goes_into_a_holding_collection(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    parts = export_of(groups=("QCode Lab",))
    carol = Person(client, db, "carol")
    record = upload(carol, parts)
    lab = owner_named(record, "QCode Lab")
    # Not a site administrator: the group cannot be created; nothing to
    # put it into.
    assert lab["can_create"] is False and lab["suggestions"] == []
    assert start(carol, record).status_code == 200
    done(carol, db, blobs, job_app, record)
    mine = _library_of(db, carol)
    holding = collection(db, mine, "QCode Lab")
    assert holding.description is not None
    assert holding.description.startswith(
        "Papers of the group “QCode Lab”, exported on "
    )
    assert "Edit collection → Owner" in holding.description
    assert titles_in(db, holding.id) == ["Paper of QCode Lab"]
    reading = collection(db, mine, "QCode Lab/Reading")
    assert titles_in(db, reading.id) == ["Paper of QCode Lab"]
    # Her own papers are not in it.
    assert titles_in(db, collection(db, mine, "Thesis").id) == ["Rain"]


def test_o3_a_site_administrator_creates_the_group(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    parts = export_of(groups=("QCode Lab",))
    admin = Person(client, db, "admin", admin=True)
    record = upload(admin, parts)
    lab = owner_named(record, "QCode Lab")
    assert lab["can_create"] is True
    owners = {lab["id"]: {"action": "create"}}
    # Nothing to compare in a group made new.
    assert preview(admin, record, owners=owners)["collections"] == []
    assert start(admin, record, owners=owners).status_code == 200
    done(admin, db, blobs, job_app, record)
    created = db.scalars(select(Group).where(Group.name == "QCode Lab")).one()
    membership = db.get(Membership, (created.id, uuid.UUID(admin.id)))
    assert membership is not None and membership.role == "admin"
    library_id = db.scalars(
        select(Library.id).where(Library.group_id == created.id)
    ).one()
    paper = db.scalars(select(Item).where(Item.title == "Paper of QCode Lab")).one()
    assert paper.library_id == library_id
    assert titles_in(db, collection(db, library_id, "Reading").id) == [
        "Paper of QCode Lab"
    ]


def nested_server(client: TestClient, db: Session, *, admin: bool) -> Person:
    """Only "Uni" here, dave its admin (or only a member)."""
    root = Person(client, db, "root2", admin=True)
    dave = Person(client, db, "dave")
    uni = group(root, "Uni", root if not admin else dave)
    if not admin:
        root.put(f"/api/groups/{uni['id']}/members/{dave.id}", {"role": "member"})
    return dave


def test_o4_nested_groups_are_created_inside_one_here(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    parts = export_of(groups=("Uni", "Uni/QCode Lab", "Uni/QCode Lab/Theory"))
    dave = nested_server(client, db, admin=True)
    record = upload(dave, parts)
    assert owner_named(record, "Uni")["can_create"] is False  # exists here
    assert owner_named(record, "Uni/QCode Lab")["can_create"] is True
    theory = owner_named(record, "Uni/QCode Lab/Theory")
    assert theory["can_create"] is True
    # "Uni" is offered as the same group (suggested only).
    assert owner_named(record, "Uni")["suggestions"][0]["likeness"] == "same"
    response = start(dave, record, owners={theory["id"]: {"action": "create"}})
    assert response.status_code == 200, response.text
    done(dave, db, blobs, job_app, record)
    groups = {g.name: g for g in db.scalars(select(Group))}
    assert groups["QCode Lab"].parent_id == groups["Uni"].id
    assert groups["Theory"].parent_id == groups["QCode Lab"].id
    for name in ("QCode Lab", "Theory"):
        assert db.get(Membership, (groups[name].id, uuid.UUID(dave.id))) is not None
    paper = db.scalars(
        select(Item).where(Item.title == "Paper of Uni/QCode Lab/Theory")
    ).one()
    theory_library = db.scalars(
        select(Library.id).where(Library.group_id == groups["Theory"].id)
    ).one()
    assert paper.library_id == theory_library
    # The other two went into holding collections in dave's library.
    mine = _library_of(db, dave)
    assert titles_in(db, collection(db, mine, "QCode Lab").id) == [
        "Paper of Uni/QCode Lab"
    ]


def test_o5_o8_no_group_where_the_person_is_no_admin(
    export_of: Export,
    client: TestClient,
    db: Session,
) -> None:
    parts = export_of(groups=("Uni", "Uni/QCode Lab"))
    dave = nested_server(client, db, admin=False)
    record = upload(dave, parts)
    lab = owner_named(record, "Uni/QCode Lab")
    assert lab["can_create"] is False
    # O8: forged anyway: refused with a clear message, nothing imported.
    response = start(dave, record, owners={lab["id"]: {"action": "create"}})
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Only the administrators of “Uni” can make groups inside it."
    )
    top = owner_named(record, "Uni")
    response = start(dave, record, owners={top["id"]: {"action": "create"}})
    assert response.status_code == 403
    assert "exists here already" in response.json()["detail"]
    carol = Person(client, db, "carol")
    record = upload(carol, parts)
    response = start(
        carol, record, owners={owner_named(record, "Uni")["id"]: {"action": "create"}}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Only site administrators can create top-level groups such as “Uni”."
    )
    assert db.scalar(select(func.count()).select_from(Item)) == 0


def test_o6_similar_groups_are_suggested_never_chosen(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    parts = export_of(groups=("QCode Lab",))
    root = Person(client, db, "root2", admin=True)
    carol = Person(client, db, "carol")
    here = group(root, "QCode-Lab", carol)
    record = upload(carol, parts)
    lab = owner_named(record, "QCode Lab")
    assert lab["suggestions"] == [
        {"library_id": here["library_id"], "name": "QCode-Lab", "likeness": "nearly"}
    ]
    assert start(carol, record).status_code == 200
    done(carol, db, blobs, job_app, record)
    paper = db.scalars(select(Item).where(Item.title == "Paper of QCode Lab")).one()
    assert paper.library_id == _library_of(db, carol)  # c, the default


def test_o7_the_holding_collection_hands_over(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    parts = export_of(groups=("QCode Lab",))
    root = Person(client, db, "root2", admin=True)
    carol = Person(client, db, "carol")
    record = upload(carol, parts)
    start(carol, record)
    done(carol, db, blobs, job_app, record)
    mine = _library_of(db, carol)
    holding = collection(db, mine, "QCode Lab")
    # Later the group exists here; carol gives it the collection.
    lab = group(root, "QCode Lab", carol)
    response = carol.patch(
        f"/api/collections/{holding.id}",
        {"library_id": lab["library_id"], "add_papers": True},
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    paper = db.scalars(select(Item).where(Item.title == "Paper of QCode Lab")).one()
    assert str(paper.library_id) == lab["library_id"]
    reading = collection(db, uuid.UUID(lab["library_id"]), "QCode Lab/Reading")
    assert titles_in(db, reading.id) == ["Paper of QCode Lab"]
    assert str(db.get_one(Collection, holding.id).library_id) == lab["library_id"]


# Tags and collections


def carols(db: Session, carol: Person) -> uuid.UUID:
    return _library_of(db, carol)


def tag_here(db: Session, owner: uuid.UUID, name: str, *, keyword: bool = False) -> Tag:
    paper = _paper(db, owner, f"Tagged {name}", f"10.2/{name.replace(' ', '')}")
    found = organize.tag_item(
        db,
        paper,
        name,
        library_id=owner,
        source=TagSource.AUTOMATIC if keyword else TagSource.MANUAL,
    )
    db.commit()
    return found


def clash(found: dict[str, Any], kind: str, name: str) -> dict[str, Any] | None:
    return next((c for c in found[kind] if c["name"] == name), None)


def test_t1_t2_t4_t5_tags(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    parts = export_of()
    carol = Person(client, db, "carol")
    mine = carols(db, carol)
    to_read = tag_here(db, mine, "to read")  # T1
    tag_here(db, mine, "to read (imported)")
    optics = tag_here(db, mine, "Optics")  # T4
    keyword = tag_here(db, mine, "Quantum Physics", keyword=True)  # T5
    record = upload(carol, parts)
    found = preview(carol, record)
    # T1: the same name: listed, merge preselected.
    t1 = clash(found, "tags", "to read")
    assert t1 is not None
    assert t1["default"] == {"action": "merge", "target_id": str(to_read.id)}
    assert t1["suggestions"][0]["likeness"] == "same"
    assert t1["suggestions"][0]["papers"] == 1
    assert t1["new_name"] == "to read (imported 2)"
    # T4: "Topics" is not like "Optics": not listed. T5: keywords never.
    assert {c["name"] for c in found["tags"]} == {"to read"}
    assert [s["name"] for s in t1["suggestions"]] == ["to read", "to read (imported)"]
    assert str(mine) in found["targets"]
    assert start(carol, record).status_code == 200
    done(carol, db, blobs, job_app, record)
    radar = db.scalars(select(Item).where(Item.title == "Radar gaps")).one()
    names = {link.tag.name: link for link in radar.tag_links}
    assert names["to read"].tag_id == to_read.id
    assert names["Quantum Physics"].tag_id == keyword.id
    assert names["Quantum Physics"].source == "automatic"
    assert names["Topics"].tag_id != optics.id


def test_t2_nearly_the_same_tag_merges(
    export_of: Export, client: TestClient, db: Session
) -> None:
    parts = export_of()
    carol = Person(client, db, "carol")
    mine = carols(db, carol)
    here = tag_here(db, mine, "to-read")
    record = upload(carol, parts)
    t2 = clash(preview(carol, record), "tags", "to read")
    assert t2 is not None
    assert t2["default"] == {"action": "merge", "target_id": str(here.id)}
    assert t2["suggestions"][0]["likeness"] == "nearly"


def test_t3_t9_similar_collection_and_mapping(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    parts = export_of()
    carol = Person(client, db, "carol")
    mine = carols(db, carol)
    phd = _collection(db, mine, "PhD")
    phd_thesis = _collection(db, mine, "Thesis", phd)
    db.commit()
    record = upload(carol, parts)
    found = preview(carol, record)
    t3 = clash(found, "collections", "Thesis")
    assert t3 is not None
    # T3: only similar: made new unless mapped; "PhD/Thesis" suggested.
    assert t3["default"] == {"action": "new", "target_id": None}
    assert t3["suggestions"][0] == {
        "id": str(phd_thesis.id),
        "name": "PhD/Thesis",
        "likeness": "similar",
        "papers": 0,
    }
    paths = [t["name"] for t in found["targets"][str(mine)]["collections"]]
    assert paths == ["PhD", "PhD/Thesis"]
    # T9: mapped to "PhD/Thesis": the papers there, "Chapter 1" inside it.
    choice = {"action": "map", "target_id": str(phd_thesis.id)}
    response = start(carol, record, collections={t3["id"]: choice})
    assert response.status_code == 200, response.text
    done(carol, db, blobs, job_app, record)
    assert titles_in(db, phd_thesis.id) == ["Rain"]
    chapter = collection(db, mine, "PhD/Thesis/Chapter 1")
    assert titles_in(db, chapter.id) == ["Radar gaps"]


def test_t6_smart_collections_merge_only_with_the_same_rules(
    export_of: Export, client: TestClient, db: Session
) -> None:
    parts = export_of()
    carol = Person(client, db, "carol")
    mine = carols(db, carol)
    topics = tag_here(db, mine, "Topics")
    smart = _collection(db, mine, "Physics", rules={"tags_any": [str(topics.id)]})
    db.commit()
    record = upload(carol, parts)
    t6 = clash(preview(carol, record), "collections", "Physics")
    assert t6 is not None and t6["smart"] and not t6["may_map"]
    assert t6["default"] == {"action": "merge", "target_id": str(smart.id)}
    smart.rules = {"tags_any": [str(topics.id)], "year_from": 2000}
    db.commit()
    t6 = clash(preview(carol, record), "collections", "Physics")
    assert t6 is not None
    assert t6["default"] == {"action": "new", "target_id": None}
    assert "other rules" in (t6["note"] or "")
    forced = {t6["id"]: {"action": "merge", "target_id": str(smart.id)}}
    assert start(carol, record, collections=forced).status_code == 422


def test_t7_t8_r1_nested_clash_all_new_and_again(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    parts = export_of()
    carol = Person(client, db, "carol")
    mine = carols(db, carol)
    thesis = _collection(db, mine, "Thesis")
    chapter = _collection(db, mine, "Chapter 1", thesis)
    to_read = tag_here(db, mine, "to read")
    tag_here(db, mine, "Quantum Physics", keyword=True)
    db.commit()
    record = upload(carol, parts)
    found = preview(carol, record)
    # T7: the clash inside the merged "Thesis" is listed by its path.
    t7 = clash(found, "collections", "Thesis/Chapter 1")
    assert t7 is not None
    assert t7["default"] == {"action": "merge", "target_id": str(chapter.id)}
    # Made new, a parent's children are not compared.
    top = clash(found, "collections", "Thesis")
    assert top is not None
    as_new = {top["id"]: {"action": "new"}}
    assert (
        clash(
            preview(carol, record, collections=as_new),
            "collections",
            "Thesis/Chapter 1",
        )
        is None
    )
    # T8: all as new.
    found = preview(carol, record, all_new=True)
    assert {c["default"]["action"] for c in found["tags"] + found["collections"]} == {
        "new"
    }
    assert start(carol, record, all_new=True).status_code == 200
    done(carol, db, blobs, job_app, record)
    imported = collection(db, mine, "Thesis (imported)")
    assert titles_in(db, imported.id) == ["Rain"]
    assert titles_in(db, collection(db, mine, "Thesis (imported)/Chapter 1").id) == [
        "Radar gaps"
    ]
    assert titles_in(db, thesis.id) == []
    tags = {t.name for t in db.scalars(select(Tag).where(Tag.library_id == mine))}
    assert "to read (imported)" in tags and "Quantum Physics (imported)" not in tags
    assert to_read.id in {t.id for t in db.scalars(select(Tag))}
    # R1: the same export with the same choices adds nothing.
    before = counts(db)
    record = upload(carol, parts)
    assert start(carol, record, all_new=True).status_code == 200
    report = done(carol, db, blobs, job_app, record)["report"]
    assert report["added"] == 0 and report["collections"] == 0
    assert counts(db) == before


def test_r1_holding_collections_are_not_made_twice(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    parts = export_of(groups=("QCode Lab",))
    carol = Person(client, db, "carol")
    mine = carols(db, carol)
    _collection(db, mine, "QCode Lab")  # her own, of the same name
    db.commit()
    for round_ in range(2):
        record = upload(carol, parts)
        assert start(carol, record).status_code == 200
        report = done(carol, db, blobs, job_app, record)["report"]
        if round_ == 0:
            before = counts(db)
        else:
            assert report["added"] == 0 and counts(db) == before
    holding = collection(db, mine, "QCode Lab (2)")
    assert titles_in(db, holding.id) == ["Paper of QCode Lab"]


def test_choices_that_cannot_be_followed(
    export_of: Export, client: TestClient, db: Session
) -> None:
    parts = export_of()
    carol = Person(client, db, "carol")
    mine = carols(db, carol)
    smart = _collection(db, mine, "Smart", rules={})
    thesis = _collection(db, mine, "Thesis")
    to_read = tag_here(db, mine, "to read")
    db.commit()
    record = upload(carol, parts)
    found = preview(carol, record)
    top = clash(found, "collections", "Thesis")
    tag = clash(found, "tags", "to read")
    assert top is not None and tag is not None
    # Into a smart collection, a collection of another library, a tag that
    # needs no choice, an owner "Me" into a holding collection.
    cases = [
        {"collections": {top["id"]: {"action": "map", "target_id": str(smart.id)}}},
        {"collections": {top["id"]: {"action": "map", "target_id": str(uuid.uuid4())}}},
        {"tags": {"nope": {"action": "new"}}},
        {"collections": {"nope": {"action": "new"}}},
        {"owners": {owner_named(record, "Me")["id"]: {"action": "collection"}}},
    ]
    for body in cases:
        assert start(carol, record, **body).status_code == 422, body
    tag_into = {tag["id"]: {"action": "map", "target_id": str(thesis.id)}}
    assert start(carol, record, tags=tag_into).status_code == 422
    good = {tag["id"]: {"action": "map", "target_id": str(to_read.id)}}
    assert start(carol, record, tags=good).status_code == 200


def test_o4_a_group_inside_the_group_its_parent_goes_into(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    """A parent mapped into a group here: the new group is made inside it,
    if the person is that group's admin."""
    parts = export_of(groups=("Uni", "Uni/QCode Lab"))
    root = Person(client, db, "root2", admin=True)
    dave = Person(client, db, "dave")
    center = group(root, "Center", dave)
    other = group(root, "Other", root)
    root.put(f"/api/groups/{other['id']}/members/{dave.id}", {"role": "member"})
    record = upload(dave, parts)
    uni, lab = owner_named(record, "Uni"), owner_named(record, "Uni/QCode Lab")

    def owners(into: dict[str, Any]) -> dict[str, Any]:
        return {
            uni["id"]: {"action": "into", "library_id": into["library_id"]},
            lab["id"]: {"action": "create"},
        }

    refused = start(dave, record, owners=owners(other))
    assert refused.status_code == 403
    assert "only where you are an administrator" in refused.json()["detail"]
    response = start(dave, record, owners=owners(center))
    assert response.status_code == 200, response.text
    done(dave, db, blobs, job_app, record)
    made = db.scalars(select(Group).where(Group.name == "QCode Lab")).one()
    assert str(made.parent_id) == center["id"]
    paper = db.scalars(select(Item).where(Item.title == "Paper of Uni")).one()
    assert str(paper.library_id) == center["library_id"]


def test_choices_checked_again_when_the_import_runs(
    export_of: Export,
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
) -> None:
    """Rights may change between choosing and running: then the import
    stops with the reason, nothing added."""
    parts = export_of(groups=("QCode Lab",))
    root = Person(client, db, "root2", admin=True)
    carol = Person(client, db, "carol")
    here = group(root, "QCode Lab", carol)
    record = upload(carol, parts)
    lab = owner_named(record, "QCode Lab")
    into = {lab["id"]: {"action": "into", "library_id": here["library_id"]}}
    assert preview(carol, record, owners=into)["tags"] == []
    forged = {lab["id"]: {"action": "into", "library_id": str(uuid.uuid4())}}
    response = carol.post(
        f"/api/imports/{record['id']}/preview", json={"owners": forged}
    )
    assert response.status_code == 404
    assert start(carol, record, owners=into).status_code == 200
    db.execute(
        update(Membership)
        .where(Membership.user_id == uuid.UUID(carol.id))
        .values(role="reader")
    )
    db.commit()
    run_imports(db, blobs, job_app)
    result = carol.get(f"/api/imports/{record['id']}").json()
    assert result["status"] == "failed"
    assert result["error"] == "You may not add papers there."
    assert db.scalar(select(func.count()).select_from(Item)) == 0
