"""Personal access tokens: create, list, revoke (only when logged in, never
with a token)."""

import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from paperus import tokens
from paperus.access import Access
from paperus.api.deps import DB, SessionUser
from paperus.models import AccessToken
from paperus.tokens import Scope

router = APIRouter(prefix="/api/me/tokens", tags=["tokens"])


class TokenOut(BaseModel):
    id: uuid.UUID
    name: str
    hint: str
    """The token's start, to recognise it."""
    scopes: list[Scope]
    library_ids: list[uuid.UUID] | None
    """Only these owners' things; everything the person may see if None."""
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class NewToken(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    scopes: list[Scope] = Field(min_length=1)
    library_ids: list[uuid.UUID] | None = None
    expires_in_days: Annotated[int | None, Field(ge=1, le=3650)] = None


class CreatedToken(TokenOut):
    token: str
    """The token itself: shown this once, store it in the client."""


def _out(token: AccessToken) -> TokenOut:
    return TokenOut(
        id=token.id,
        name=token.name,
        hint=token.hint,
        scopes=[Scope(s) for s in token.scopes],
        library_ids=(
            [uuid.UUID(i) for i in token.library_ids]
            if token.library_ids is not None
            else None
        ),
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
    )


@router.get("")
def list_tokens(db: DB, user: SessionUser) -> list[TokenOut]:
    rows = db.scalars(
        select(AccessToken)
        .where(AccessToken.user_id == user.id)
        .order_by(AccessToken.created_at.desc())
    )
    return [_out(token) for token in rows]


@router.post("", status_code=201)
def create_token(body: NewToken, db: DB, user: SessionUser) -> CreatedToken:
    """A token acting as you, narrowed to its scopes (and owners)."""
    if body.library_ids is not None:
        access = Access.of(db, user)
        if not body.library_ids or not all(map(access.can_read, body.library_ids)):
            raise HTTPException(422, "choose owners you belong to")
    token, raw = tokens.create_token(
        db,
        user,
        body.name.strip(),
        body.scopes,
        library_ids=body.library_ids,
        expires_in=timedelta(days=body.expires_in_days)
        if body.expires_in_days
        else None,
    )
    db.commit()
    return CreatedToken(**_out(token).model_dump(), token=raw)


@router.delete("/{token_id}", status_code=204)
def revoke_token(token_id: uuid.UUID, db: DB, user: SessionUser) -> Response:
    token = db.get(AccessToken, token_id)
    if token is None or token.user_id != user.id:
        raise HTTPException(404, "token not found")
    db.delete(token)
    db.commit()
    return Response(status_code=204)
