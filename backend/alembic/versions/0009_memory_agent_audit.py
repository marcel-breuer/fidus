"""Add memories, agent settings, pending agent actions and the audit log."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.config import get_settings

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def _secure_table(table: str, role: str, privileges: str = "SELECT, INSERT, UPDATE, DELETE") -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_owner ON {table} "
        "USING (user_id = current_setting('app.user_id', true)) "
        "WITH CHECK (user_id = current_setting('app.user_id', true))"
    )
    op.execute(f'GRANT {privileges} ON {table} TO "{role}"')


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    user_fk = sa.ForeignKey("users.id", ondelete="CASCADE")
    op.create_table(
        "memories",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), user_fk, nullable=False),
        sa.Column("content", sa.String(1000), nullable=False),
        sa.Column("source", sa.String(20), server_default="user", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("source IN ('user', 'agent')", name="ck_memories_source"),
    )
    op.create_index("ix_memories_user_id", "memories", ["user_id"])
    op.create_table(
        "agent_settings",
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("write_mode", sa.String(10), server_default="ask", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("write_mode IN ('ask', 'allow')", name="ck_agent_settings_write_mode"),
    )
    op.create_table(
        "agent_actions",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "conversation_id", sa.String(26), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("message_id", sa.String(26), sa.ForeignKey("messages.id", ondelete="CASCADE")),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'failed')", name="ck_agent_actions_status"
        ),
    )
    op.create_index("ix_agent_actions_user_id", "agent_actions", ["user_id"])
    op.create_index("ix_agent_actions_conversation", "agent_actions", ["user_id", "conversation_id"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor", sa.String(20), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(26)),
        sa.Column("details", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    role = _app_role()
    for table in ("memories", "agent_settings", "agent_actions"):
        _secure_table(table, role)
    # Append-only for the application role: the audit trail cannot be edited or removed by the app.
    _secure_table("audit_log", role, "SELECT, INSERT")


def downgrade() -> None:
    for table in ("audit_log", "agent_actions", "agent_settings", "memories"):
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
        op.drop_table(table)
