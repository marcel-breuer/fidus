import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.config import get_settings
from app.db.models import FileVersion, Node, Task
from app.db.session import system_session, user_session
from app.worker.broker import broker
from app.worker.tasks import count_open_tasks


@pytest.fixture
async def two_users(owner_engine) -> tuple[str, str]:
    async with owner_engine.begin() as conn:
        accounts = (
            ("01HAAAAAAAAAAAAAAAAAAAAAAA", "a@example.com"),
            ("01HBBBBBBBBBBBBBBBBBBBBBBB", "b@example.com"),
        )
        for uid, mail in accounts:
            await conn.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, is_active, is_superuser, is_verified) "
                    "VALUES (:id, :email, 'x', true, false, false)"
                ),
                {"id": uid, "email": mail},
            )
    await owner_engine.dispose()
    return "01HAAAAAAAAAAAAAAAAAAAAAAA", "01HBBBBBBBBBBBBBBBBBBBBBBB"


async def _add_task(user_id: str, title: str) -> str:
    async with user_session(user_id) as session:
        task = Task(user_id=user_id, title=title)
        session.add(task)
        await session.flush()
        return task.id


async def test_no_context_returns_no_rows(two_users) -> None:
    a, _ = two_users
    await _add_task(a, "mine")
    async with system_session() as session:
        assert (await session.scalars(text("SELECT id FROM tasks"))).all() == []


async def test_files_tables_return_no_rows_without_context(two_users) -> None:
    a, _ = two_users
    async with user_session(a) as session:
        node = Node(user_id=a, kind="file", name="private.txt")
        session.add(node)
        await session.flush()
        session.add(FileVersion(
            user_id=a, node_id=node.id, version=1, storage_key=f"{a}/01ARZ3NDEKTSV4RRFFQ69G5FAV",
            size_bytes=4, mime_type="text/plain", sha256="a" * 64,
        ))
    async with system_session() as session:
        assert (await session.scalars(text("SELECT id FROM nodes"))).all() == []
        assert (await session.scalars(text("SELECT id FROM file_versions"))).all() == []


async def test_user_reads_only_own_rows(two_users) -> None:
    a, b = two_users
    await _add_task(a, "a-task")
    await _add_task(b, "b-task")
    async with user_session(a) as session:
        titles = (await session.scalars(text("SELECT title FROM tasks"))).all()
    assert titles == ["a-task"]


async def test_user_cannot_update_other_users_rows(two_users) -> None:
    a, b = two_users
    task_id = await _add_task(b, "b-task")
    async with user_session(a) as session:
        result = await session.execute(
            text("UPDATE tasks SET title = 'hijacked' WHERE id = :id"), {"id": task_id}
        )
        assert result.rowcount == 0
    async with user_session(b) as session:
        assert await session.scalar(text("SELECT title FROM tasks WHERE id = :id"), {"id": task_id}) == "b-task"


async def test_user_cannot_delete_other_users_rows(two_users) -> None:
    a, b = two_users
    task_id = await _add_task(b, "b-task")
    async with user_session(a) as session:
        result = await session.execute(text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})
        assert result.rowcount == 0
    async with user_session(b) as session:
        assert await session.scalar(text("SELECT count(*) FROM tasks")) == 1


async def test_user_cannot_insert_rows_for_another_user(two_users) -> None:
    a, b = two_users
    with pytest.raises(DBAPIError):
        await _add_task_as(a, b)


async def _add_task_as(context_user: str, owner: str) -> None:
    async with user_session(context_user) as session:
        session.add(Task(user_id=owner, title="forged"))


async def test_user_can_update_and_delete_own_rows(two_users) -> None:
    a, _ = two_users
    task_id = await _add_task(a, "mine")
    async with user_session(a) as session:
        updated = await session.execute(text("UPDATE tasks SET title = 'new' WHERE id = :id"), {"id": task_id})
        assert updated.rowcount == 1
        deleted = await session.execute(text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})
        assert deleted.rowcount == 1


async def test_context_does_not_leak_between_transactions(two_users) -> None:
    a, _ = two_users
    await _add_task(a, "mine")
    async with system_session() as session:
        assert await session.scalar(text("SELECT count(*) FROM tasks")) == 0


async def test_application_role_has_no_privileged_attributes() -> None:
    async with system_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
    assert tuple(row) == (False, False, False, False)


async def test_application_role_is_test_specific() -> None:
    async with system_session() as session:
        role = await session.scalar(text("SELECT current_user"))
    assert role == get_settings().app_db_user
    assert role.endswith("_test")


async def test_application_role_cannot_disable_policies() -> None:
    async with system_session() as session:
        with pytest.raises(ProgrammingError):
            await session.execute(text("ALTER TABLE tasks DISABLE ROW LEVEL SECURITY"))


async def test_application_role_cannot_drop_policy_or_become_owner() -> None:
    async with system_session() as session:
        with pytest.raises(ProgrammingError):
            await session.execute(text("DROP POLICY tasks_owner ON tasks"))
    async with system_session() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("SET ROLE postgres"))


async def test_rls_is_forced_on_user_owned_tables(owner_engine) -> None:
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'tasks'")
            )
        ).one()
    assert tuple(row) == (True, True)


async def test_files_rls_is_forced(owner_engine) -> None:
    async with owner_engine.connect() as conn:
        rows = (await conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('nodes', 'file_versions') ORDER BY relname"
            )
        )).all()
    assert rows == [(True, True), (True, True)]


async def test_application_role_does_not_own_tables(owner_engine) -> None:
    async with owner_engine.connect() as conn:
        owner = await conn.scalar(text("SELECT tableowner FROM pg_tables WHERE tablename = 'tasks'"))
        app_role = await conn.scalar(
            text("SELECT rolname FROM pg_roles WHERE rolname = :role"), {"role": get_settings().app_db_user}
        )
    assert app_role is not None and owner != app_role


async def test_worker_job_runs_in_owning_users_context(two_users) -> None:
    a, b = two_users
    await _add_task(a, "one")
    await _add_task(a, "two")
    await _add_task(b, "other")
    assert await count_open_tasks(a) == 2
    assert await count_open_tasks(b) == 1


async def test_worker_job_is_registered_on_the_broker() -> None:
    assert broker.find_task("tasks.count_open") is not None
