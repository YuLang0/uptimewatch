from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Monitor, Notification, NotificationDelivery, NotificationSettings, User
from app.security.auth import hash_password
from app.services.checker import CheckOutcome

T0 = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)


async def make_user(db: AsyncSession, email: str = "owner@example.com") -> User:
    user = User(email=email, password_hash=hash_password("password-123"), display_name="")
    db.add(user)
    await db.flush()
    return user


async def make_monitor(db: AsyncSession, user: User, **kw) -> Monitor:
    defaults = dict(
        name="테스트 사이트",
        url="https://public.example/",
        interval_seconds=60,
        timeout_seconds=10,
        failure_threshold=3,
        recovery_threshold=1,
        status="pending",
        consecutive_failures=0,
        consecutive_successes=0,
        is_active=True,
        next_check_at=T0,
        created_at=T0 - timedelta(days=60),
    )
    defaults.update(kw)
    monitor = Monitor(user_id=user.id, **defaults)
    db.add(monitor)
    await db.flush()
    return monitor


async def set_notification_settings(db: AsyncSession, user: User, **kw) -> None:
    ns = NotificationSettings(
        user_id=user.id,
        email_enabled=kw.get("email_enabled", True),
        email_to=kw.get("email_to"),
        email_cooldown_minutes=kw.get("email_cooldown_minutes", 10),
        reminder_interval_minutes=kw.get("reminder_interval_minutes", 0),
        tls_warning_days=kw.get("tls_warning_days", 14),
    )
    db.add(ns)
    await db.flush()


def up(at: datetime, ms: int = 120, **kw) -> CheckOutcome:
    return CheckOutcome(outcome="up", checked_at=at, status_code=200, response_time_ms=ms, **kw)


def down(at: datetime, error_type: str = "status", status_code: int | None = 500) -> CheckOutcome:
    return CheckOutcome(
        outcome="down",
        checked_at=at,
        status_code=status_code,
        response_time_ms=50,
        error_type=error_type,
        error_message="예상하지 않은 HTTP 상태 코드 500" if error_type == "status" else "타임아웃",
    )


def unknown(at: datetime) -> CheckOutcome:
    return CheckOutcome(outcome="error", checked_at=at, error_type="internal", error_message="검사기 내부 오류")


async def notification_kinds(db: AsyncSession, user_id: int) -> list[str]:
    rows = await db.scalars(select(Notification.kind).where(Notification.user_id == user_id).order_by(Notification.id))
    return list(rows.all())


async def delivery_statuses(db: AsyncSession, user_id: int) -> list[tuple[str, str]]:
    rows = await db.execute(
        select(NotificationDelivery.kind, NotificationDelivery.status)
        .where(NotificationDelivery.user_id == user_id)
        .order_by(NotificationDelivery.id)
    )
    return [tuple(r) for r in rows.all()]


async def count(db: AsyncSession, model, *where) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*where)) or 0)
