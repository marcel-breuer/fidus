"""REST adapter for the per-user usage counters (read only)."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_user_scoped_session
from app.auth.manager import current_active_user
from app.db.models import User
from app.services import usage

router = APIRouter(tags=["usage"])


class UsageAmounts(BaseModel):
    chat_requests: int
    input_tokens: int
    output_tokens: int
    transcription_minutes: float
    embedding_chunks: int
    mcp_calls: int

    @classmethod
    def from_metrics(cls, values: dict[str, int]) -> "UsageAmounts":
        return cls(
            chat_requests=values[usage.CHAT_REQUESTS],
            input_tokens=values[usage.INPUT_TOKENS],
            output_tokens=values[usage.OUTPUT_TOKENS],
            transcription_minutes=round(values[usage.TRANSCRIPTION_SECONDS] / 60, 1),
            embedding_chunks=values[usage.EMBEDDING_CHUNKS],
            mcp_calls=values[usage.MCP_CALLS],
        )


class UsageDayOut(UsageAmounts):
    day: date


class UsageOut(BaseModel):
    start: date
    end: date
    totals: UsageAmounts
    daily: list[UsageDayOut]


@router.get("/usage", response_model=UsageOut)
async def get_usage(
    days: int = Query(default=usage.DEFAULT_DAYS, ge=1, le=usage.MAX_DAYS),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> UsageOut:
    result = await usage.summary(session, user, days)
    return UsageOut(
        start=result.start,
        end=result.end,
        totals=UsageAmounts.from_metrics(result.totals),
        daily=[
            UsageDayOut(day=item.day, **UsageAmounts.from_metrics(item.amounts).model_dump())
            for item in result.days
        ],
    )
