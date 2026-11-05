"""Profile pictures: one's own to set, everyone's to see when logged in."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from sqlalchemy import select

from paperus import avatars
from paperus.api.auth import UserOut, user_out
from paperus.api.deps import DB, CurrentUser, SessionUser
from paperus.models import User

router = APIRouter(tags=["avatars"])


@router.put("/api/me/avatar")
async def set_avatar(
    upload: Annotated[UploadFile, File()], db: DB, user: SessionUser
) -> UserOut:
    """One's profile picture: PNG, JPEG or WebP, up to 256 KB (the website
    sends it square, 256 pixels wide)."""
    data = await upload.read(avatars.MAX_BYTES + 1)
    try:
        avatars.set_avatar(user, data)
    except avatars.BadPicture as error:
        raise HTTPException(422, str(error)) from error
    db.commit()
    return user_out(user)


@router.delete("/api/me/avatar")
def remove_avatar(db: DB, user: SessionUser) -> UserOut:
    avatars.set_avatar(user, None)
    db.commit()
    return user_out(user)


@router.get(
    "/api/users/{user_id}/avatar",
    response_class=Response,
    responses={200: {"content": {"image/*": {}}}},
)
def get_avatar(user_id: uuid.UUID, db: DB, viewer: CurrentUser) -> Response:
    """A person's profile picture (404 without one). Its address carries
    the picture's version, so it may be kept for long."""
    row = db.execute(
        select(User.avatar, User.avatar_type).where(User.id == user_id)
    ).first()
    if row is None or row.avatar is None or row.avatar_type is None:
        raise HTTPException(404, "no picture")
    return Response(
        row.avatar,
        media_type=row.avatar_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
