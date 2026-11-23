"""Add instance-wide settings, starting with the runtime registration mode.

This table is not user-owned, so it has no user_id and intentionally has no RLS policy.
"""

import sqlalchemy as sa

from alembic import op
from app.config import get_settings

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def upgrade() -> None:
    op.create_table(
        "instance_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(26), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON instance_settings TO "{_app_role()}"')


def downgrade() -> None:
    op.drop_table("instance_settings")
