"""Add extracted documents and vector/full-text chunks for Files Stage 2."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.config import get_settings

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


class Vector1536(sa.types.UserDefinedType):
    def get_col_spec(self, **kwargs: object) -> str:
        return "vector(1536)"


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
        "documents",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(26), sa.ForeignKey("nodes.id", ondelete="CASCADE")),
        sa.Column("version_id", sa.String(26), sa.ForeignKey("file_versions.id", ondelete="CASCADE"), unique=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("error_code", sa.String(50)),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source IN ('upload', 'memo', 'agent')", name="ck_documents_source"),
        sa.CheckConstraint("status IN ('pending', 'ready', 'failed')", name="ck_documents_status"),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"])
    op.create_index("ix_documents_node_id", "documents", ["node_id"])
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(26), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector1536(), nullable=False),
        sa.Column(
            "search", postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', content)", persisted=True), nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_id", "position", name="uq_chunks_document_position"),
    )
    op.create_index("ix_chunks_user_id", "chunks", ["user_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_embedding_hnsw", "chunks", ["embedding"], postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"})
    op.create_index("ix_chunks_search", "chunks", ["search"], postgresql_using="gin")
    role = _app_role()
    _secure_table("documents", role)
    _secure_table("chunks", role)


def downgrade() -> None:
    for table in ("chunks", "documents"):
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
        op.drop_table(table)
