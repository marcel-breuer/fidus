from datetime import datetime

from fastapi_users.db import SQLAlchemyBaseUserTable
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_id


class User(SQLAlchemyBaseUserTable[str], TimestampMixin, Base):
    """Account row. Not row-level-secured: authentication has to look users up before
    any user context exists. Everything a user owns references it through user_id."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)


class Task(TimestampMixin, Base):
    """Example user-owned table proving the row-level-security pattern."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
