"""Add personal access tokens with a hash-only lookup function."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.config import get_settings

revision = "0011"
# Chained after 0009 (memory, agent actions, audit log).
down_revision = "0009"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(50)), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("cardinality(scopes) > 0", name="ck_api_tokens_scopes_not_empty"),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])
    op.execute("ALTER TABLE api_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE api_tokens FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY api_tokens_owner ON api_tokens "
        "USING (user_id = current_setting('app.user_id', true)) "
        "WITH CHECK (user_id = current_setting('app.user_id', true))"
    )
    role = _app_role()
    # Tokens are revoked, never deleted by the application role.
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON api_tokens TO "{role}"')
    # Bearer authentication has to resolve a token before any user context exists. This reviewed
    # SECURITY DEFINER function accepts only the SHA-256 hash, returns the owner and scopes of a
    # valid token (unrevoked, unexpired, active user) and records last use at most once a minute.
    op.execute(
        """CREATE FUNCTION authenticate_api_token(p_token_hash text)
        RETURNS TABLE(token_id text, user_id text, scopes text[])
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public AS $$
            WITH hit AS (
                SELECT t.id FROM public.api_tokens AS t
                JOIN public.users AS u ON u.id = t.user_id
                WHERE t.token_hash = p_token_hash
                  AND t.revoked_at IS NULL AND t.expires_at > now() AND u.is_active
            ), touched AS (
                UPDATE public.api_tokens AS t SET last_used_at = now()
                FROM hit
                WHERE t.id = hit.id
                  AND (t.last_used_at IS NULL OR t.last_used_at < now() - interval '1 minute')
                RETURNING t.id
            )
            SELECT t.id, t.user_id, t.scopes FROM public.api_tokens AS t JOIN hit ON hit.id = t.id
        $$"""
    )
    op.execute("REVOKE ALL ON FUNCTION authenticate_api_token(text) FROM PUBLIC")
    op.execute(f'GRANT EXECUTE ON FUNCTION authenticate_api_token(text) TO "{role}"')


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS authenticate_api_token(text)")
    op.execute("DROP POLICY IF EXISTS api_tokens_owner ON api_tokens")
    op.drop_table("api_tokens")
