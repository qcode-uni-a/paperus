"""Profile pictures: small images the website has already cut to a square
and scaled down; kept in the database (so backups have them)."""

import hashlib
import uuid

from paperus.models import User

MAX_BYTES = 256 * 1024
# Recognised by their first bytes, whatever the upload claims.
_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}


class BadPicture(ValueError):
    pass


def image_type(data: bytes) -> str:
    """The picture's media type; BadPicture if it is none we take."""
    if len(data) > MAX_BYTES:
        raise BadPicture(f"the picture is larger than {MAX_BYTES // 1024} KB")
    for signature, media_type in _SIGNATURES.items():
        if data.startswith(signature):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise BadPicture("only PNG, JPEG or WebP pictures")


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
