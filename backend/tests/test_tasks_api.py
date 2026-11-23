from datetime import UTC, datetime

import httpx

from app.db.models import Reminder, Task
from app.db.session import get_sessionmaker, set_user_context
from tests.helpers import PASSWORD, register


async def _login(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""


async def test_task_routes_authentication_csrf_and_cross_user_access(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/tasks")).status_code == 401
    first = await register(client, "tasks-api-a@example.com")
    assert first.status_code == 201
    await _login(client, "tasks-api-a@example.com")
    missing_csrf = await client.post("/api/v1/tasks", json={"title": "Denied"}, headers={"X-CSRF-Token": "bad"})
    assert missing_csrf.status_code == 403
    created = await client.post("/api/v1/tasks", json={"title": "Private", "notes": "Owner only"})
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert (await client.post(f"/api/v1/tasks/{task_id}/complete")).status_code == 200

    second = await register(client, "tasks-api-b@example.com")
    assert second.status_code == 201
    await _login(client, "tasks-api-b@example.com")
    assert (await client.get(f"/api/v1/tasks/{task_id}")).status_code == 404
    assert (await client.patch(f"/api/v1/tasks/{task_id}", json={"title": "Steal"})).status_code == 404
    assert (await client.delete(f"/api/v1/tasks/{task_id}")).status_code == 404
    assert (await client.post(f"/api/v1/tasks/{task_id}/reopen")).status_code == 404
    assert (await client.get("/api/v1/tasks")).json()["items"] == []


async def test_reminder_routes_and_module_guard(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/reminders")).status_code == 401
    assert (await client.get("/api/v1/reminders/stream")).status_code == 401
    response = await register(client, "task-module-admin@example.com")
    assert response.status_code == 201
    await _login(client, "task-module-admin@example.com")
    created = await client.post("/api/v1/tasks", json={"title": "Module task"})
    assert created.status_code == 201
    # Disabled modules block every task capability while leaving the stored task intact.
    disabled = await client.put("/api/v1/admin/modules/tasks", json={"enabled": False})
    assert disabled.status_code == 200
    assert (await client.get("/api/v1/tasks")).status_code == 404
    assert (await client.get("/api/v1/reminders/stream")).status_code == 404
    enabled = await client.put("/api/v1/admin/modules/tasks", json={"enabled": True})
    assert enabled.status_code == 200
    assert (await client.get("/api/v1/tasks")).status_code == 200


async def test_reminder_route_cannot_list_or_dismiss_another_users_reminder(client: httpx.AsyncClient) -> None:
    owner = await register(client, "reminder-api-owner@example.com")
    assert owner.status_code == 201
    await _login(client, "reminder-api-owner@example.com")
    owner_id = owner.json()["id"]
    now = datetime(2026, 11, 23, 12, tzinfo=UTC)
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, owner_id)
        task = Task(user_id=owner_id, title="Owned reminder", remind_at=now)
        session.add(task)
        await session.flush()
        reminder = Reminder(user_id=owner_id, task_id=task.id, due_at=now, state="pending")
        session.add(reminder)
        await session.flush()
        reminder_id = reminder.id

    other = await register(client, "reminder-api-other@example.com")
    assert other.status_code == 201
    await _login(client, "reminder-api-other@example.com")
    assert (await client.get("/api/v1/reminders")).json() == []
    assert (await client.post(f"/api/v1/reminders/{reminder_id}/dismiss")).status_code == 404
