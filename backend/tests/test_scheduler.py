from app.worker.scheduler import scheduler
from app.worker.tasks import purge_expired_auth_sessions


def test_expired_session_purge_has_daily_utc_schedule() -> None:
    assert purge_expired_auth_sessions.labels["schedule"] == [{"cron": "15 3 * * *"}]
    assert scheduler is not None
