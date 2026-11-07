"""Profile pictures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from paperus import avatars
from tests.people import Person, group


def png(width: int = 256, height: int = 256) -> bytes:
    header = b"\x00\x00\x00\x0dIHDR" + width.to_bytes(4) + height.to_bytes(4)
    return b"\x89PNG\r\n\x1a\n" + header + b"\x00" * 200


def jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 9
    frame = b"\xff\xc0\x00\x11\x08" + height.to_bytes(2) + width.to_bytes(2)
    return b"\xff\xd8" + app0 + frame + b"\x00" * 200


def webp(width: int, height: int) -> bytes:
    lossy = b"\x00" * 6 + width.to_bytes(2, "little") + height.to_bytes(2, "little")
    return b"RIFF\x00\x00\x00\x00WEBPVP8 \x00\x00\x00\x00" + lossy + b"\x00" * 200


PNG = png()
WEBP = webp(256, 256)


def put(person: Person, data: bytes, name: str = "me.png") -> dict:
    response = person.client.put(
        "/api/me/avatar",
        headers=person.headers,
        files={"upload": (name, data, "image/png")},
    )
    return {"status": response.status_code, **response.json()}


def test_set_see_and_remove(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    ben = Person(client, db, "ben")
    me = put(ada, PNG)
    assert me["status"] == 200
    url = me["avatar_url"]
    assert url.startswith(f"/api/users/{ada.id}/avatar?v=")
    assert ada.get("/api/auth/me").json()["avatar_url"] == url

    seen = ben.get(url)
    assert seen.status_code == 200
    assert seen.content == PNG
    assert seen.headers["content-type"] == "image/png"
    assert "immutable" in seen.headers["cache-control"]
    assert seen.headers["x-content-type-options"] == "nosniff"
    client.cookies.clear()
    assert client.get(url).status_code == 401

    # A new picture, a new address.
    assert put(ada, WEBP, "me.webp")["avatar_url"] != url
    assert (
        ben.get(f"/api/users/{ada.id}/avatar").headers["content-type"] == "image/webp"
    )

    assert ada.delete("/api/me/avatar").json()["avatar_url"] is None
    assert ben.get(f"/api/users/{ada.id}/avatar").status_code == 404


def test_only_small_pictures(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    svg = put(ada, b"<svg xmlns='http://www.w3.org/2000/svg'/>", "x.svg")
    assert svg["status"] == 422
    assert "PNG, JPEG or WebP" in svg["detail"]
    big = put(ada, PNG + b"\x00" * 300_000)
    assert big["status"] == 422


def test_shown_with_members_and_users(client: TestClient, db: Session) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    chair = group(root, "Chair", ada)
    url = put(ada, PNG)["avatar_url"]
    members = ada.get(f"/api/groups/{chair['id']}/members").json()
    assert members[0]["avatar_url"] == url
    users = {u["username"]: u for u in root.get("/api/admin/users").json()}
    assert users["ada"]["avatar_url"] == url
    assert users["root"]["avatar_url"] is None


def test_sizes_are_read() -> None:
    assert avatars.dimensions(png(300, 200), "image/png") == (300, 200)
    assert avatars.dimensions(jpeg(640, 480), "image/jpeg") == (640, 480)
    assert avatars.dimensions(webp(128, 96), "image/webp") == (128, 96)
    # Lossless WebP: 14 bits each, less one.
    bits = (128 - 1) | ((96 - 1) << 14)
    lossless = (
        b"RIFF\x00\x00\x00\x00WEBPVP8L"
        + b"\x00" * 5
        + bits.to_bytes(4, "little")
        + b"\x00" * 20
    )
    assert avatars.dimensions(lossless, "image/webp") == (128, 96)
    # Extended WebP: 24 bits each, less one.
    extended = (
        b"RIFF\x00\x00\x00\x00WEBPVP8X"
        + b"\x00" * 8
        + (128 - 1).to_bytes(3, "little")
        + (96 - 1).to_bytes(3, "little")
    )
    assert avatars.dimensions(extended, "image/webp") == (128, 96)


def test_unreadable_sizes() -> None:
    for data, media_type in (
        (png()[:12] + b"IEND" + b"\x00" * 20, "image/png"),
        # JPEG segments that do not start with 0xFF, or no frame header.
        (b"\xff\xd8\x00\xe0" + b"\x00" * 30, "image/jpeg"),
        (
            b"\xff\xd8" + b"\xff\xe0\x00\x0a" + b"\x00" * 8 + b"\xff\xd9" * 8,
            "image/jpeg",
        ),
        (b"RIFF\x00\x00\x00\x00WEBPVP8Z" + b"\x00" * 20, "image/webp"),
        # Cut off in the header (it would read as 1 x 1 pixels).
        (b"RIFF\x00\x00\x00\x00WEBPVP8L\x00", "image/webp"),
    ):
        with pytest.raises(avatars.BadPicture, match="size cannot be read"):
            avatars.dimensions(data, media_type)


def test_no_full_size_photos(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    for big in (png(4000, 3000), jpeg(1024, 1024), webp(600, 600)):
        refused = put(ada, big)
        assert refused["status"] == 422
        assert "at most 512" in refused["detail"]
    assert put(ada, jpeg(512, 512))["status"] == 200
