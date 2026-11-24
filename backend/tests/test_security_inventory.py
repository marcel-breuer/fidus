"""Schema-level guards: a new table or SECURITY DEFINER function cannot slip in unreviewed.

These tests read the migrated scratch database through the owner role and fail with a message
that names the object, so the author has to either secure it or add it to the reviewed lists
below together with the reasoning in docs/security-review.md."""

import pytest
from sqlalchemy import text

from app.config import get_settings

# Tables that carry user_id but are intentionally not row-level-secured: authentication has to
# read them before any user context exists.
USER_ID_WITHOUT_RLS = {"sessions"}
# Tables without a user_id column. `invitations` is secured through its creator column.
NO_USER_ID_EXPECTED = {"alembic_version", "instance_settings", "module_settings", "users", "invitations"}
SECURED_WITHOUT_USER_ID = {"invitations"}

# The complete, reviewed SECURITY DEFINER inventory: name -> argument list.
REVIEWED_DEFINER_FUNCTIONS = {
    "admin_list_audit_entries": "p_before_created_at timestamp with time zone, p_before_id text, p_row_limit integer",
    "admin_list_invitations": "",
    "admin_revoke_invitation": "p_invitation_id text",
    "authenticate_api_token": "p_token_hash text",
    "consume_invitation": "p_token_hash text, p_user_id text",
    "invitation_is_valid": "p_token_hash text",
    "users_with_due_tasks": "p_now timestamp with time zone",
}

TABLES = """
SELECT c.relname AS name, c.relrowsecurity AS rls, c.relforcerowsecurity AS forced,
       EXISTS (SELECT 1 FROM information_schema.columns k WHERE k.table_schema = 'public'
               AND k.table_name = c.relname AND k.column_name = 'user_id') AS has_user_id,
       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY c.relname
"""


async def _rows(owner_engine, query: str, **params: object) -> list[dict]:  # type: ignore[no-untyped-def]
    async with owner_engine.connect() as conn:
        return [dict(row) for row in (await conn.execute(text(query), params)).mappings()]


async def test_every_user_owned_table_has_forced_rls_and_a_policy(owner_engine) -> None:  # type: ignore[no-untyped-def]
    tables = await _rows(owner_engine, TABLES)
    assert len(tables) > 15  # guards against the query silently matching nothing
    problems = []
    for table in tables:
        if table["has_user_id"] and table["name"] not in USER_ID_WITHOUT_RLS:
            if not (table["rls"] and table["forced"] and table["policies"] >= 1):
                problems.append(f"{table['name']}: user_id without forced RLS and a policy")
    assert not problems, "; ".join(problems)


async def test_tables_without_user_id_are_reviewed(owner_engine) -> None:  # type: ignore[no-untyped-def]
    tables = await _rows(owner_engine, TABLES)
    unreviewed = {t["name"] for t in tables if not t["has_user_id"]} - NO_USER_ID_EXPECTED
    assert not unreviewed, f"table(s) without user_id need a review and an entry here: {sorted(unreviewed)}"
    for table in tables:
        if table["name"] in SECURED_WITHOUT_USER_ID:
            assert table["rls"] and table["forced"] and table["policies"] >= 1, table["name"]


async def test_exempt_user_id_tables_are_exactly_the_reviewed_ones(owner_engine) -> None:  # type: ignore[no-untyped-def]
    tables = {t["name"]: t for t in await _rows(owner_engine, TABLES)}
    for name in USER_ID_WITHOUT_RLS:
        assert not tables[name]["rls"], f"{name} gained RLS; remove it from the exemption list"
    without_rls = {name for name, t in tables.items() if t["has_user_id"] and not t["rls"]}
    assert without_rls == USER_ID_WITHOUT_RLS


async def test_application_role_has_no_elevated_attributes(owner_engine) -> None:  # type: ignore[no-untyped-def]
    role = get_settings().app_db_user
    rows = await _rows(
        owner_engine,
        "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication FROM pg_roles WHERE rolname = :r",
        r=role,
    )
    assert rows and not any(rows[0].values())


async def test_application_role_owns_nothing_and_cannot_alter_policies(owner_engine) -> None:  # type: ignore[no-untyped-def]
    role = get_settings().app_db_user
    owned = await _rows(
        owner_engine,
        "SELECT c.relname FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
        "WHERE r.rolname = :r AND c.relnamespace = 'public'::regnamespace",
        r=role,
    )
    assert owned == []


async def test_security_definer_inventory_is_exactly_the_reviewed_set(owner_engine) -> None:  # type: ignore[no-untyped-def]
    functions = await _rows(
        owner_engine,
        "SELECT p.proname AS name, pg_get_function_arguments(p.oid) AS args, p.proconfig AS config, "
        "pg_get_userbyid(p.proowner) AS owner, p.proacl::text AS acl "
        "FROM pg_proc p WHERE p.prosecdef AND p.pronamespace = 'public'::regnamespace",
    )
    assert {f["name"]: f["args"] for f in functions} == REVIEWED_DEFINER_FUNCTIONS
    app_role = get_settings().app_db_user
    for function in functions:
        # A pinned search_path prevents a user-created object from shadowing a table or operator.
        assert function["config"] and "search_path=public" in function["config"], function["name"]
        # PUBLIC execution is revoked: an ACL entry with an empty grantee ("=X/...") would grant it.
        assert function["acl"] and "{=" not in function["acl"] and ",=" not in function["acl"], function["name"]
        assert f"{app_role}=X/" in function["acl"], function["name"]
        assert function["owner"] != app_role
        grants = await _rows(
            owner_engine,
            "SELECT r.rolname FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a "
            "JOIN pg_roles r ON r.oid = a.grantee "
            "WHERE p.proname = :name AND a.privilege_type = 'EXECUTE'",
            name=function["name"],
        )
        assert {row["rolname"] for row in grants} == {app_role, function["owner"]}, function["name"]


@pytest.mark.parametrize("table", ["api_tokens", "usage_records", "audit_log"])
async def test_append_only_tables_cannot_be_deleted_by_the_application_role(owner_engine, table: str) -> None:  # type: ignore[no-untyped-def]
    role = get_settings().app_db_user
    rows = await _rows(owner_engine, "SELECT has_table_privilege(:r, :t, 'DELETE') AS can", r=role, t=table)
    assert rows[0]["can"] is False
