"""장애 판정 상태 머신: 일시적 장애 vs 연속 장애, 복구 감지, 중복 알림 방지."""

from __future__ import annotations

from datetime import timedelta

from app.config import Settings
from app.models import CheckResult, Incident
from app.services.monitoring import record_check
from tests.helpers import (
    T0,
    count,
    delivery_statuses,
    down,
    make_monitor,
    make_user,
    notification_kinds,
    set_notification_settings,
    unknown,
    up,
)

M = timedelta(minutes=1)


async def test_transient_failure_does_not_open_incident(sessionmaker, test_settings) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user, failure_threshold=3)
        await record_check(db, monitor, up(T0), test_settings)
        await record_check(db, monitor, down(T0 + M), test_settings)
        await record_check(db, monitor, down(T0 + 2 * M), test_settings)  # 2회 < 기준 3회
        await record_check(db, monitor, up(T0 + 3 * M), test_settings)
        await db.commit()

        assert monitor.status == "up"
        assert monitor.consecutive_failures == 0
        assert await count(db, Incident) == 0
        assert await notification_kinds(db, user.id) == []
        assert await count(db, CheckResult, CheckResult.outcome == "down") == 2  # 실패 자체는 기록됨


async def test_consecutive_failures_open_incident_once(sessionmaker, test_settings) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user, failure_threshold=3)
        await record_check(db, monitor, up(T0), test_settings)
        r1 = await record_check(db, monitor, down(T0 + M), test_settings)
        r2 = await record_check(db, monitor, down(T0 + 2 * M), test_settings)
        r3 = await record_check(db, monitor, down(T0 + 3 * M), test_settings)
        assert r1.incident_opened is None and r2.incident_opened is None
        assert r3.incident_opened is not None

        incident = r3.incident_opened
        assert incident.started_at == T0 + M  # 첫 실패 시각
        assert incident.detected_at == T0 + 3 * M  # 기준 도달 시각
        assert monitor.status == "down"

        # 장애가 계속되어도 알림·장애 기록은 추가되지 않음 (반복 알림 방지)
        for i in range(4, 15):
            res = await record_check(db, monitor, down(T0 + i * M), test_settings)
            assert res.notifications == []
        await db.commit()
        assert await count(db, Incident) == 1
        assert await notification_kinds(db, user.id) == ["down"]
        assert incident.failed_checks == 14


async def test_recovery_is_detected_with_duration(sessionmaker, test_settings) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user, failure_threshold=2, recovery_threshold=2)
        await record_check(db, monitor, down(T0), test_settings)
        await record_check(db, monitor, down(T0 + M), test_settings)
        assert monitor.status == "down"

        # 복구 기준 2회: 첫 성공만으로는 복구 아님
        r = await record_check(db, monitor, up(T0 + 5 * M), test_settings)
        assert r.incident_resolved is None and monitor.status == "down"
        r = await record_check(db, monitor, up(T0 + 6 * M), test_settings)
        assert r.incident_resolved is not None
        incident = r.incident_resolved
        assert incident.resolved_at == T0 + 5 * M  # 연속 성공의 첫 성공 시각
        assert incident.duration_seconds == 5 * 60
        assert monitor.status == "up"
        await db.commit()
        assert await notification_kinds(db, user.id) == ["down", "up"]


async def test_failure_streak_interrupted_by_success_resets(sessionmaker, test_settings) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user, failure_threshold=3)
        for i, outcome in enumerate([down, down, up, down, down, up, down, down]):
            await record_check(db, monitor, outcome(T0 + i * M), test_settings)
        await db.commit()
        assert await count(db, Incident) == 0


async def test_unknown_results_do_not_change_state(sessionmaker, test_settings) -> None:
    """측정 불가(error)는 실패로도 성공으로도 세지 않는다."""
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user, failure_threshold=2)
        await record_check(db, monitor, down(T0), test_settings)
        await record_check(db, monitor, unknown(T0 + M), test_settings)
        assert monitor.consecutive_failures == 1
        await record_check(db, monitor, down(T0 + 2 * M), test_settings)
        assert monitor.status == "down"
        await record_check(db, monitor, unknown(T0 + 3 * M), test_settings)
        assert monitor.status == "down"  # 측정 불가로 복구 처리하지 않음
        await db.commit()


async def test_flapping_emails_are_rate_limited(sessionmaker, test_settings) -> None:
    """장애↔복구가 반복될 때 같은 종류 이메일은 제한 시간 안에 한 번만 발송."""
    settings = test_settings.model_copy(update={"smtp_host": "smtp.example", "smtp_from": "uw@example.com"})
    async with sessionmaker() as db:
        user = await make_user(db)
        await set_notification_settings(db, user, email_cooldown_minutes=30)
        monitor = await make_monitor(db, user, failure_threshold=1)
        t = T0
        for _ in range(3):  # down → up 3회 반복 (각 2분 간격)
            await record_check(db, monitor, down(t), settings)
            await record_check(db, monitor, up(t + M), settings)
            t += 2 * M
        await db.commit()

        # 대시보드 알림은 상태 전이마다 기록 (장애 3건 각각의 down/up)
        assert await notification_kinds(db, user.id) == ["down", "up"] * 3
        assert await count(db, Incident) == 3
        # 이메일은 첫 down/up 만 발송 대기, 나머지는 중복 제한으로 억제 기록
        assert await delivery_statuses(db, user.id) == [
            ("down", "pending"),
            ("up", "pending"),
            ("down", "suppressed"),
            ("up", "suppressed"),
            ("down", "suppressed"),
            ("up", "suppressed"),
        ]


async def test_email_marked_skipped_when_smtp_not_configured(sessionmaker, test_settings) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user, failure_threshold=1)
        await record_check(db, monitor, down(T0), test_settings)
        await db.commit()
        assert await delivery_statuses(db, user.id) == [("down", "skipped")]


async def test_email_disabled_by_user_creates_no_delivery(sessionmaker, test_settings) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        await set_notification_settings(db, user, email_enabled=False)
        monitor = await make_monitor(db, user, failure_threshold=1)
        await record_check(db, monitor, down(T0), test_settings)
        await db.commit()
        assert await notification_kinds(db, user.id) == ["down"]
        assert await delivery_statuses(db, user.id) == []


async def test_reminders_respect_interval(sessionmaker, test_settings) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        await set_notification_settings(db, user, reminder_interval_minutes=30)
        monitor = await make_monitor(db, user, failure_threshold=1)
        for i in range(0, 95):  # 95분 동안 매분 실패
            await record_check(db, monitor, down(T0 + i * M), test_settings)
        await db.commit()
        # 장애 판정(0분) 후 30, 60, 90분에 재알림 3회
        assert await notification_kinds(db, user.id) == ["down", "reminder", "reminder", "reminder"]


async def test_tls_expiry_warning_once_per_certificate(sessionmaker, test_settings) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user)
        expiry = T0 + timedelta(days=10)
        for i in range(5):
            await record_check(db, monitor, up(T0 + i * M, tls_expires_at=expiry), test_settings)
        # 인증서 갱신(새 만료일) 후 다시 임박 → 새 경고
        far = T0 + timedelta(days=200)
        await record_check(db, monitor, up(T0 + 10 * M, tls_expires_at=far), test_settings)
        await db.commit()
        assert await notification_kinds(db, user.id) == ["tls_expiring"]
        assert monitor.tls_expires_at == far


async def test_incident_duplicate_notification_is_idempotent(sessionmaker, test_settings: Settings) -> None:
    """같은 dedupe_key 로 알림을 두 번 만들면 두 번째는 무시된다(재처리·경쟁 상황 대비)."""
    from app.services.notifications import create_notification

    async with sessionmaker() as db:
        user = await make_user(db)
        first, _ = await create_notification(
            db, user_id=user.id, kind="down", title="t", message="m", settings=test_settings, now=T0,
            dedupe_key="incident:1:down",
        )
        second, second_delivery = await create_notification(
            db, user_id=user.id, kind="down", title="t", message="m", settings=test_settings, now=T0,
            dedupe_key="incident:1:down",
        )
        await db.commit()
        assert first is not None
        assert second is None and second_delivery is None
        assert await notification_kinds(db, user.id) == ["down"]
