"""Add instance-wide module settings.

This table is not user-owned, so it has no user_id and intentionally has no RLS policy.
"""

import sqlalchemy as sa

from alembic import op
from app.config import get_settings

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def upgrade() -> None:
    op.create_table(
        "module_settings",
        sa.Column("module_key", sa.String(100), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(26), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    role = _app_role()
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON module_settings TO "{role}"')


def downgrade() -> None:
    op.drop_table("module_settings")
