"""Add invitations and narrowly scoped registration functions."""

import sqlalchemy as sa

from alembic import op
from app.config import get_settings

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column(
            "created_by", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("used_by", sa.String(26), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_invitations_created_by", "invitations", ["created_by"])
    op.execute("ALTER TABLE invitations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE invitations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY invitations_owner ON invitations "
        "USING (created_by = current_setting('app.user_id', true)) "
        "WITH CHECK (created_by = current_setting('app.user_id', true))"
    )

    op.execute(
        """CREATE FUNCTION invitation_is_valid(p_token_hash text) RETURNS boolean
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            SELECT EXISTS (
                SELECT 1 FROM public.invitations
                WHERE token_hash = p_token_hash AND used_at IS NULL AND expires_at > now()
            )
        $$"""
    )
    op.execute(
        """CREATE FUNCTION consume_invitation(p_token_hash text, p_user_id text) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        BEGIN
            UPDATE public.invitations
            SET used_at = now(), used_by = p_user_id, updated_at = now()
            WHERE token_hash = p_token_hash AND used_at IS NULL AND expires_at > now();
            RETURN FOUND;
        END
        $$"""
    )
    op.execute("REVOKE ALL ON FUNCTION invitation_is_valid(text) FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION consume_invitation(text, text) FROM PUBLIC")

    role = _app_role()
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON invitations TO "{role}"')
    op.execute(f'GRANT EXECUTE ON FUNCTION invitation_is_valid(text) TO "{role}"')
    op.execute(f'GRANT EXECUTE ON FUNCTION consume_invitation(text, text) TO "{role}"')


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS consume_invitation(text, text)")
    op.execute("DROP FUNCTION IF EXISTS invitation_is_valid(text)")
    op.execute("DROP POLICY IF EXISTS invitations_owner ON invitations")
    op.drop_table("invitations")
