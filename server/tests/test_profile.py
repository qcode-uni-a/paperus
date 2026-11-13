"""One's account: a display name others see, and one's ORCID iD."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus.models import Author
from tests.people import Person, group


def test_display_name_and_orcid(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    chair = group(root, "Chair", ada)
    ada.put(f"/api/groups/{chair['id']}/members/{bob.id}", json={"role": "reader"})
    me = ada.put(
        "/api/auth/profile",
        {
            "display_name": "  Ada Lovelace ",
            "orcid": "https://orcid.org/0000-0002-1825-0097",
        },
    ).json()
    assert (me["display_name"], me["orcid"], me["author_id"]) == (
        "Ada Lovelace",
        "0000-0002-1825-0097",
        None,
    )
    # Others see the display name: among the group's members, as who added
    # a paper, when looking people up.
    members = bob.get(f"/api/groups/{chair['id']}/members").json()
    assert [m["display_name"] for m in members] == ["Ada Lovelace", None]
    paper = ada.add("Notes on the engine", chair["library_id"])
    added = bob.get(f"/api/items/{paper['id']}").json()["added_by"]
    assert added["display_name"] == "Ada Lovelace"
    found = root.get("/api/users", params={"q": "lovelace"}).json()
    assert [p["username"] for p in found] == ["ada"]

    # The author with that iD is her.
    author = Author(
        name="Ada Lovelace", key="ada lovelace", orcid="0000-0002-1825-0097"
    )
    db.add(author)
    db.commit()
    assert ada.get("/api/auth/me").json()["author_id"] == str(author.id)

    # A wrong check digit, or no iD at all, is refused; empty clears both.
    for wrong in ("0000-0002-1825-0098", "Ada"):
        refused = ada.put("/api/auth/profile", {"orcid": wrong})
        assert refused.status_code == 422, wrong
    cleared = ada.put("/api/auth/profile", {"display_name": "", "orcid": ""}).json()
    assert (cleared["display_name"], cleared["orcid"]) == (None, None)
