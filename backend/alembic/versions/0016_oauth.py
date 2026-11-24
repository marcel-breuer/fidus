"""Add OAuth clients, single-use authorization codes and scoped grants."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.config import get_settings

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def _secure(table: str, role: str, privileges: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_owner ON {table} "
        "USING (user_id = current_setting('app.user_id', true)) "
        "WITH CHECK (user_id = current_setting('app.user_id', true))"
    )
    op.execute(f'GRANT {privileges} ON {table} TO "{role}"')


def upgrade() -> None:
    role = _app_role()
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(64), primary_key=True),
        sa.Column("client_name", sa.String(100), nullable=False),
        sa.Column("redirect_uris", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("cardinality(redirect_uris) BETWEEN 1 AND 20", name="redirect_count"),
    )
    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(64), sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("resource", sa.String(500), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(50)), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("cardinality(scopes) > 0", name="scopes_not_empty"),
    )
    op.create_index("ix_oauth_authorization_codes_user_id", "oauth_authorization_codes", ["user_id"])
    op.create_table(
        "oauth_grants",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(64), sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource", sa.String(500), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(50)), nullable=False),
        sa.Column("access_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("cardinality(scopes) > 0", name="scopes_not_empty"),
    )
    op.create_index("ix_oauth_grants_user_id", "oauth_grants", ["user_id"])
    op.create_index("ix_oauth_grants_user_client", "oauth_grants", ["user_id", "client_id"])
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON oauth_clients TO "{role}"')
    _secure("oauth_authorization_codes", role, "SELECT, INSERT, UPDATE")
    _secure("oauth_grants", role, "SELECT, INSERT, UPDATE")

    # Bearer lookup must occur before an RLS user context exists. Inputs are token hashes and
    # the canonical resource URI only; OAuth credentials are audience-bound to the MCP server.
    op.execute(
        """CREATE FUNCTION authenticate_oauth_access(p_token_hash text, p_resource text)
        RETURNS TABLE(token_id text, user_id text, scopes text[])
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT g.id::text, g.user_id::text, g.scopes::text[]
            FROM public.oauth_grants AS g JOIN public.users AS u ON u.id = g.user_id
            WHERE g.access_token_hash = p_token_hash AND g.resource = p_resource
              AND g.revoked_at IS NULL AND g.access_expires_at > now() AND u.is_active
        $$"""
    )
    op.execute("REVOKE ALL ON FUNCTION authenticate_oauth_access(text, text) FROM PUBLIC")
    op.execute(f'GRANT EXECUTE ON FUNCTION authenticate_oauth_access(text, text) TO "{role}"')
    op.execute(
        """CREATE FUNCTION oauth_lookup_code(p_hash text)
        RETURNS TABLE(code_id text, user_id text, client_id text, redirect_uri text, resource text, scopes text[], challenge text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT c.id, c.user_id, c.client_id, c.redirect_uri, c.resource, c.scopes, c.code_challenge
            FROM public.oauth_authorization_codes AS c
            JOIN public.users AS u ON u.id = c.user_id
            WHERE c.code_hash = p_hash AND c.used_at IS NULL AND c.expires_at > now() AND u.is_active
        $$"""
    )
    op.execute(
        """CREATE FUNCTION oauth_lookup_refresh(p_hash text)
        RETURNS TABLE(grant_id text, user_id text, client_id text, resource text, scopes text[])
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT g.id, g.user_id, g.client_id, g.resource, g.scopes
            FROM public.oauth_grants AS g JOIN public.users AS u ON u.id = g.user_id
            WHERE g.refresh_token_hash = p_hash AND g.revoked_at IS NULL
              AND g.refresh_expires_at > now() AND u.is_active
        $$"""
    )
    # RFC 7009 revocation accepts an opaque credential without a logged-in browser session.
    # This function reveals no owner data and writes the matching user's audit row atomically.
    op.execute(
        """CREATE FUNCTION oauth_revoke_token(p_hash text)
        RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public AS $$
        DECLARE affected integer;
        DECLARE owner_id text;
        BEGIN
            SELECT g.user_id INTO owner_id FROM public.oauth_grants AS g
            WHERE g.revoked_at IS NULL AND (g.access_token_hash = p_hash OR g.refresh_token_hash = p_hash)
            LIMIT 1;
            UPDATE public.oauth_grants SET revoked_at = now(), updated_at = now()
            WHERE revoked_at IS NULL AND (access_token_hash = p_hash OR refresh_token_hash = p_hash);
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected > 0 THEN
                PERFORM set_config('app.user_id', owner_id, true);
                INSERT INTO public.audit_log (id, user_id, actor, action, target_type, target_id, details)
                SELECT substr(md5(random()::text || clock_timestamp()::text), 1, 26), g.user_id,
                       'user', 'oauth.revoke', 'oauth_grant', g.id,
                       jsonb_build_object('client_id', g.client_id)
                FROM public.oauth_grants AS g WHERE g.revoked_at IS NOT NULL
                  AND (g.access_token_hash = p_hash OR g.refresh_token_hash = p_hash);
            END IF;
            RETURN affected > 0;
        END $$"""
    )
    for signature in (
        "authenticate_oauth_access(text, text)", "oauth_lookup_code(text)",
        "oauth_lookup_refresh(text)", "oauth_revoke_token(text)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f'GRANT EXECUTE ON FUNCTION {signature} TO "{role}"')


def downgrade() -> None:
    for signature in (
        "oauth_revoke_token(text)", "oauth_lookup_refresh(text)",
        "oauth_lookup_code(text)", "authenticate_oauth_access(text, text)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    for table in ("oauth_grants", "oauth_authorization_codes"):
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
        op.drop_table(table)
    op.drop_table("oauth_clients")
