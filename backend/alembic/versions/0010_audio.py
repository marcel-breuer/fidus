"""Add user-owned voice memos for the audio module."""

import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision = "0010"
# Chained after 0008 while 0009 is developed in parallel; the merge fixes the chain.
down_revision = "0008"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def upgrade() -> None:
    op.create_table(
        "memos",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("error_code", sa.String(50)),
        sa.Column("audio_key", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.String(10)),
        sa.Column("document_id", sa.String(26), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("speech_key", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'transcribing', 'ready', 'failed')", name="ck_memos_status"),
    )
    op.create_index("ix_memos_user_id", "memos", ["user_id"])
    op.create_index("ix_memos_document_id", "memos", ["document_id"])
    role = _app_role()
    op.execute("ALTER TABLE memos ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE memos FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY memos_owner ON memos "
        "USING (user_id = current_setting('app.user_id', true)) "
        "WITH CHECK (user_id = current_setting('app.user_id', true))"
    )
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON memos TO "{role}"')


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS memos_owner ON memos")
    op.drop_table("memos")
