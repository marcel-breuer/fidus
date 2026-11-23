"""Add task details and per-user in-app reminders."""

import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision = "0005t"
down_revision = "0004"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def upgrade() -> None:
    op.add_column("tasks", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "reminders",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(26), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("state IN ('pending', 'shown', 'dismissed')", name="reminder_state"),
        sa.UniqueConstraint("task_id", "due_at", name="uq_reminders_task_id_due_at"),
    )
    op.create_index("ix_reminders_user_id", "reminders", ["user_id"])
    op.create_index("ix_reminders_task_id", "reminders", ["task_id"])
    op.execute("ALTER TABLE reminders ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reminders FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY reminders_owner ON reminders "
        "USING (user_id = current_setting('app.user_id', true)) "
        "WITH CHECK (user_id = current_setting('app.user_id', true))"
    )
    role = _app_role()
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON reminders TO "{role}"')
    op.execute(
        """CREATE FUNCTION users_with_due_tasks(p_now timestamptz) RETURNS SETOF text
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT DISTINCT t.user_id FROM public.tasks AS t
            WHERE t.remind_at <= p_now AND t.done_at IS NULL AND t.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM public.reminders AS r
                  WHERE r.task_id = t.id AND r.due_at = t.remind_at
              )
        $$"""
    )
    op.execute("REVOKE ALL ON FUNCTION users_with_due_tasks(timestamptz) FROM PUBLIC")
    op.execute(f'GRANT EXECUTE ON FUNCTION users_with_due_tasks(timestamptz) TO "{role}"')


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS users_with_due_tasks(timestamptz)")
    op.execute("DROP POLICY IF EXISTS reminders_owner ON reminders")
    op.drop_table("reminders")
    op.drop_column("tasks", "deleted_at")
    op.drop_column("tasks", "due_at")
    op.drop_column("tasks", "notes")
