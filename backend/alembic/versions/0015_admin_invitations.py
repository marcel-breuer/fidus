"""Allow admins to manage instance invitations and read instance audit metadata."""

from alembic import op
from app.config import get_settings

revision = "0015"
down_revision = "0013"
branch_labels = None
depends_on = None


def _app_role() -> str:
    role = get_settings().app_db_user
    if not role.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER may only contain letters, digits and underscores")
    return role


def upgrade() -> None:
    op.execute(
        """CREATE FUNCTION admin_list_invitations()
        RETURNS TABLE(id text, expires_at timestamptz)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            SELECT i.id, i.expires_at
            FROM public.invitations AS i
            WHERE i.used_at IS NULL AND i.expires_at > now()
              AND EXISTS (
                SELECT 1 FROM public.users AS u
                WHERE u.id = current_setting('app.user_id', true)
                  AND u.is_superuser AND u.is_active
              )
            ORDER BY i.created_at DESC, i.id DESC
        $$"""
    )
    op.execute(
        """CREATE FUNCTION admin_revoke_invitation(p_invitation_id text)
        RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM public.users AS u
                WHERE u.id = current_setting('app.user_id', true)
                  AND u.is_superuser AND u.is_active
            ) THEN
                RETURN false;
            END IF;
            DELETE FROM public.invitations
            WHERE id = p_invitation_id AND used_at IS NULL;
            RETURN FOUND;
        END
        $$"""
    )
    op.execute(
        """CREATE FUNCTION admin_list_audit_entries(
            p_before_created_at timestamptz, p_before_id text, p_row_limit integer
        ) RETURNS TABLE(
            id text, user_id text, actor text, action text, target_type text,
            target_id text, created_at timestamptz
        ) LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            SELECT a.id, a.user_id, a.actor, a.action, a.target_type, a.target_id, a.created_at
            FROM public.audit_log AS a
            WHERE EXISTS (
                SELECT 1 FROM public.users AS u
                WHERE u.id = current_setting('app.user_id', true)
                  AND u.is_superuser AND u.is_active
            )
              AND (p_before_created_at IS NULL OR a.created_at < p_before_created_at
                   OR (a.created_at = p_before_created_at AND a.id < p_before_id))
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT LEAST(GREATEST(p_row_limit, 1), 101)
        $$"""
    )

    op.execute("REVOKE ALL ON FUNCTION admin_list_invitations() FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION admin_revoke_invitation(text) FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION admin_list_audit_entries(timestamptz, text, integer) FROM PUBLIC")
    role = _app_role()
    op.execute(f'GRANT EXECUTE ON FUNCTION admin_list_invitations() TO "{role}"')
    op.execute(f'GRANT EXECUTE ON FUNCTION admin_revoke_invitation(text) TO "{role}"')
    op.execute(
        f'GRANT EXECUTE ON FUNCTION admin_list_audit_entries(timestamptz, text, integer) TO "{role}"'
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS admin_list_audit_entries(timestamptz, text, integer)")
    op.execute("DROP FUNCTION IF EXISTS admin_revoke_invitation(text)")
    op.execute("DROP FUNCTION IF EXISTS admin_list_invitations()")
