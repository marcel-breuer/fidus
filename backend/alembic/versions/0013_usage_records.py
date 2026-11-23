"""Add per-user, per-day usage counters (display only, no quota enforcement)."""

import sqlalchemy as sa

from alembic import op
from app.config import get_settings

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("metric", sa.String(40), nullable=False),
        sa.Column("quantity", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "metric IN ('chat_requests', 'input_tokens', 'output_tokens', 'transcription_seconds', "
            "'embedding_chunks', 'mcp_calls')",
            name="ck_usage_records_metric",
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_records_quantity"),
        sa.UniqueConstraint("user_id", "day", "metric", name="uq_usage_records_user_day_metric"),
    )
    op.create_index("ix_usage_records_user_id", "usage_records", ["user_id"])
    op.execute("ALTER TABLE usage_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE usage_records FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY usage_records_owner ON usage_records "
        "USING (user_id = current_setting('app.user_id', true)) "
        "WITH CHECK (user_id = current_setting('app.user_id', true))"
    )
    # Counters only grow through the service; the application role never deletes them.
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON usage_records TO "{_app_role()}"')


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS usage_records_owner ON usage_records")
    op.drop_table("usage_records")
