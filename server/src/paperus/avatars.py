"""Profile pictures: small images the website has already cut to a square
and scaled down; kept in the database (so backups have them)."""

import hashlib
import uuid

from paperus.models import User

MAX_BYTES = 256 * 1024
# Never a full-size photo: the website sends 256 x 256.
MAX_SIDE = 512
# Recognised by their first bytes, whatever the upload claims.
_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}


class BadPicture(ValueError):
    pass


def image_type(data: bytes) -> str:
    """The picture's media type; BadPicture if it is none we take, or
    larger than ``MAX_SIDE`` pixels on a side."""
    if len(data) > MAX_BYTES:
        raise BadPicture(f"the picture is larger than {MAX_BYTES // 1024} KB")
    media_type = _media_type(data)
    width, height = dimensions(data, media_type)
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
        raise BadPicture(
            f"the picture is {width} x {height} pixels; at most {MAX_SIDE} on a side"
        )
    return media_type


def _media_type(data: bytes) -> str:
    for signature, media_type in _SIGNATURES.items():
        if data.startswith(signature):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise BadPicture("only PNG, JPEG or WebP pictures")


def dimensions(data: bytes, media_type: str) -> tuple[int, int]:
    """Width and height, read from the picture's header."""
    try:
        if media_type == "image/png":
            if data[12:16] == b"IHDR":
                return _big(data[16:20]), _big(data[20:24])
        elif media_type == "image/jpeg":
            return _jpeg_size(data)
        elif data[12:16] == b"VP8 ":
            return _little(data[26:28]) & 0x3FFF, _little(data[28:30]) & 0x3FFF
        elif data[12:16] == b"VP8L":
            bits = _little(data[21:25])
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        elif data[12:16] == b"VP8X":
            return _little(data[24:27]) + 1, _little(data[27:30]) + 1
    except IndexError:
        pass
    raise BadPicture("the picture's size cannot be read")


def _big(raw: bytes) -> int:
    return int.from_bytes(raw, "big")


def _little(raw: bytes) -> int:
    return int.from_bytes(raw, "little")


# JPEG frame headers (SOF0 to SOF15, except DHT, JPG and DAC) hold the size.
_FRAMES = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _jpeg_size(data: bytes) -> tuple[int, int]:
    at = 2
    while at + 9 < len(data):
        if data[at] != 0xFF:
            raise IndexError
        marker = data[at + 1]
        if marker in _FRAMES:
            return _big(data[at + 7 : at + 9]), _big(data[at + 5 : at + 7])
        at += 2 + _big(data[at + 2 : at + 4])
    raise IndexError


def set_avatar(user: User, data: bytes | None) -> None:
    if data is None:
        user.avatar = user.avatar_type = user.avatar_version = None
        return
    user.avatar_type = image_type(data)
    user.avatar = data
    user.avatar_version = hashlib.sha256(data).hexdigest()[:16]


def avatar_url(user_id: uuid.UUID, version: str | None) -> str | None:
    """Where the website loads it; the version keeps caches right."""
    return f"/api/users/{user_id}/avatar?v={version}" if version else None
