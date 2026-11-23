"""REST adapters for personal access tokens. Cookie sessions only: a token cannot mint tokens."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_user_scoped_session
from app.auth.manager import current_active_user
from app.db.models import ApiToken, User
from app.services import api_tokens

router = APIRouter(tags=["tokens"])

# Mirrors app.modules.registry.ALL_SCOPES; a test keeps the two in step.
Scope = Literal[
    "audio:read", "audio:write", "chat:use", "files:read", "files:write", "tasks:read", "tasks:write"
]


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Scope] = Field(min_length=1)
    expires_in_days: int = Field(default=api_tokens.DEFAULT_EXPIRY_DAYS, ge=1, le=api_tokens.MAX_EXPIRY_DAYS)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name cannot be blank")
        return value


class TokenOut(BaseModel):
    id: str
    name: str
    token_prefix: str
    scopes: list[Scope]
    expires_at: datetime
    last_used_at: datetime | None
    created_at: datetime

    @classmethod
    def from_model(cls, item: ApiToken) -> "TokenOut":
        return cls.model_validate(item, from_attributes=True)


class TokenCreated(TokenOut):
    token: str


@router.post("/tokens", response_model=TokenCreated, status_code=201)
async def post_token(
    body: TokenCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> TokenCreated:
    try:
        item, secret = await api_tokens.create_token(
            session, user, body.name, list(body.scopes), body.expires_in_days
        )
    except api_tokens.TokenLimitError as exc:
        raise HTTPException(status_code=409, detail="TOKEN_LIMIT_REACHED") from exc
    return TokenCreated(**TokenOut.from_model(item).model_dump(), token=secret)


@router.get("/tokens", response_model=list[TokenOut])
async def get_tokens(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[TokenOut]:
    return [TokenOut.from_model(item) for item in await api_tokens.list_tokens(session, user)]


@router.delete("/tokens/{token_id}", status_code=204)
async def delete_token(
    token_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> Response:
    if not await api_tokens.revoke_token(session, user, token_id):
        raise HTTPException(status_code=404, detail="TOKEN_NOT_FOUND")
    return Response(status_code=204)
