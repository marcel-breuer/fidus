"""Store private chat message attachments."""

import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def upgrade() -> None:
    op.create_table(
        "message_attachments",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(26), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.String(26), sa.ForeignKey("messages.id", ondelete="CASCADE")),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False, unique=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("extracted_text", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "mime_type IN ('application/pdf', 'text/plain', 'text/markdown', 'image/png', 'image/jpeg', 'image/webp')",
            name="ck_message_attachments_mime_type",
        ),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 10485760", name="ck_message_attachments_size"),
    )
    for column in ("user_id", "conversation_id", "message_id"):
        op.create_index(f"ix_message_attachments_{column}", "message_attachments", [column])
    op.execute("ALTER TABLE message_attachments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE message_attachments FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY message_attachments_owner ON message_attachments "
        "USING (user_id = current_setting('app.user_id', true)) "
        "WITH CHECK (user_id = current_setting('app.user_id', true))"
    )
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON message_attachments TO "{_app_role()}"')


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS message_attachments_owner ON message_attachments")
    op.drop_table("message_attachments")
