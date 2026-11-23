"""Usage counters per user and UTC day. Display only: nothing here enforces a quota."""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageRecord, User
from app.db.session import user_session

logger = logging.getLogger(__name__)

CHAT_REQUESTS = "chat_requests"
INPUT_TOKENS = "input_tokens"
OUTPUT_TOKENS = "output_tokens"
TRANSCRIPTION_SECONDS = "transcription_seconds"
EMBEDDING_CHUNKS = "embedding_chunks"
MCP_CALLS = "mcp_calls"

METRICS = (CHAT_REQUESTS, INPUT_TOKENS, OUTPUT_TOKENS, TRANSCRIPTION_SECONDS, EMBEDDING_CHUNKS, MCP_CALLS)
MAX_DAYS = 90
DEFAULT_DAYS = 30


async def add(session: AsyncSession, user_id: str, amounts: dict[str, int], day: date | None = None) -> None:
    """Increment counters in the caller's transaction. Zero amounts are skipped."""
    today = day or datetime.now(UTC).date()
    for metric, quantity in amounts.items():
        if metric not in METRICS:
            raise ValueError(f"Unknown usage metric: {metric}")
        if quantity <= 0:
            continue
        statement = insert(UsageRecord).values(user_id=user_id, day=today, metric=metric, quantity=quantity)
        await session.execute(statement.on_conflict_do_update(
            constraint="uq_usage_records_user_day_metric",
            set_={"quantity": UsageRecord.quantity + statement.excluded.quantity, "updated_at": datetime.now(UTC)},
        ))


async def record(user_id: str, **amounts: int) -> None:
    """Own-transaction variant for call sites that have no open session. A counter failure
    must never break the feature being counted, so errors are logged and swallowed."""
    try:
        async with user_session(user_id) as session:
            await add(session, user_id, amounts)
    except Exception:
        logger.warning("Could not record usage", extra={"user_id": user_id})


@dataclass(frozen=True)
class UsageDay:
    day: date
    amounts: dict[str, int]


@dataclass(frozen=True)
class UsageSummary:
    start: date
    end: date
    totals: dict[str, int]
    days: list[UsageDay]


async def summary(
    session: AsyncSession, user: User, days: int = DEFAULT_DAYS, today: date | None = None
) -> UsageSummary:
    """Totals and per-day amounts for the last `days` days including today, newest day first."""
    days = max(1, min(days, MAX_DAYS))
    end = today or datetime.now(UTC).date()
    start = end - timedelta(days=days - 1)
    rows = (await session.scalars(
        select(UsageRecord)
        .where(UsageRecord.user_id == user.id, UsageRecord.day >= start, UsageRecord.day <= end)
        .order_by(UsageRecord.day.desc())
    )).all()
    totals = dict.fromkeys(METRICS, 0)
    by_day: dict[date, dict[str, int]] = {}
    for row in rows:
        totals[row.metric] += row.quantity
        by_day.setdefault(row.day, dict.fromkeys(METRICS, 0))[row.metric] = row.quantity
    return UsageSummary(start, end, totals, [UsageDay(d, by_day[d]) for d in sorted(by_day, reverse=True)])
