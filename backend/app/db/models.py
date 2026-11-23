from datetime import datetime

from fastapi_users.db import SQLAlchemyBaseUserTable
from sqlalchemy import Boolean, CheckConstraint, Computed, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
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


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated_id", "user_id", "updated_at", "id"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system', 'tool')", name="role"),
        Index("ix_messages_search", "search", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[dict | list | None] = mapped_column(JSONB)
    citations: Mapped[dict | list | None] = mapped_column(JSONB)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    search: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', content)", persisted=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invitation(TimestampMixin, Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    created_by: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[str | None] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="SET NULL")
    )


class ModuleSetting(Base):
    """Instance-wide module enablement; intentionally not user-owned or RLS protected."""

    __tablename__ = "module_settings"

    module_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="SET NULL")
    )


class Session(Base):
    """Authentication session; read before a user context exists, like users."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
