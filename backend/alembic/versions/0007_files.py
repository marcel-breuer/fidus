"""Add the Stage 1 user-owned Files tree and versions."""

import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def _secure_table(table: str, role: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_owner ON {table} "
        "USING (user_id = current_setting('app.user_id', true)) "
        "WITH CHECK (user_id = current_setting('app.user_id', true))"
    )
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO "{role}"')


def upgrade() -> None:
    op.create_table(
        "nodes",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.String(26), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('folder', 'file')", name="ck_nodes_kind"),
    )
    op.create_index("ix_nodes_user_id", "nodes", ["user_id"])
    op.create_index(
        "uq_nodes_user_parent_name_live",
        "nodes",
        ["user_id", sa.text("coalesce(parent_id, '')"), "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "file_versions",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(26), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("node_id", "version", name="uq_file_versions_node_version"),
    )
    op.create_index("ix_file_versions_user_id", "file_versions", ["user_id"])
    op.create_index("ix_file_versions_node_id", "file_versions", ["node_id"])
    role = _app_role()
    _secure_table("nodes", role)
    _secure_table("file_versions", role)


def downgrade() -> None:
    for table in ("file_versions", "nodes"):
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
        op.drop_table(table)
