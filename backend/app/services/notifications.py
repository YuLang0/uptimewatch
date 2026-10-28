"""알림 생성·중복 제한·이메일 발송 기록.

- 대시보드 알림은 상태 전이(장애/복구) 시점에만 생성되며 dedupe_key 로 중복 생성을 막습니다.
- 이메일은 '발송 기록(notification_deliveries)'을 먼저 만들고(outbox), 작업자가 비동기로 발송합니다.
  실패 시 재시도하며 최종 실패·미연동·중복 제한도 모두 기록합니다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Notification, NotificationDelivery, NotificationSettings, User
from app.services.email import EmailNotConfiguredError, EmailSender, EmailSendError

logger = logging.getLogger(__name__)

SMTP_NOT_CONFIGURED = "SMTP 미연동: SMTP_HOST·SMTP_FROM 등 환경변수를 설정하면 이메일이 발송됩니다."
RETRY_BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15))


def format_local(dt: datetime | None, settings: Settings) -> str:
    if dt is None:
        return "-"
    return dt.astimezone(ZoneInfo(settings.display_timezone)).strftime("%Y-%m-%d %H:%M:%S %Z")


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}일")
    if hours:
        parts.append(f"{hours}시간")
    if minutes:
        parts.append(f"{minutes}분")
    if secs or not parts:
        parts.append(f"{secs}초")
    return " ".join(parts)


async def get_notification_settings(db: AsyncSession, user_id: int) -> NotificationSettings:
    ns = await db.get(NotificationSettings, user_id)
    if ns is None:
        ns = NotificationSettings(
            user_id=user_id,
            email_enabled=True,
            email_to=None,
            email_cooldown_minutes=10,
            reminder_interval_minutes=0,
            tls_warning_days=14,
        )
    return ns


async def create_notification(
    db: AsyncSession,
    *,
    user_id: int,
    kind: str,
    title: str,
    message: str,
    settings: Settings,
    now: datetime,
    monitor_id: int | None = None,
    incident_id: int | None = None,
    dedupe_key: str | None = None,
    send_email: bool = True,
    bypass_cooldown: bool = False,
) -> tuple[Notification | None, NotificationDelivery | None]:
    """알림을 생성합니다. dedupe_key 가 이미 존재하면 (None, None) 을 반환합니다."""
    stmt = (
        pg_insert(Notification)
        .values(
            user_id=user_id,
            monitor_id=monitor_id,
            incident_id=incident_id,
            kind=kind,
            title=title[:200],
            message=message,
            dedupe_key=dedupe_key,
            created_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_notifications_user_dedupe")
        .returning(Notification.id)
    )
    notification_id = (await db.execute(stmt)).scalar_one_or_none()
    if notification_id is None:
        return None, None
    notification = await db.get(Notification, notification_id)
    delivery = None
    if send_email:
        delivery = await plan_email_delivery(
            db,
            user_id=user_id,
            notification_id=notification_id,
            monitor_id=monitor_id,
            kind=kind,
            settings=settings,
            now=now,
            bypass_cooldown=bypass_cooldown,
        )
    return notification, delivery


async def plan_email_delivery(
    db: AsyncSession,
    *,
    user_id: int,
    notification_id: int,
    monitor_id: int | None,
    kind: str,
    settings: Settings,
    now: datetime,
    bypass_cooldown: bool = False,
) -> NotificationDelivery | None:
    ns = await get_notification_settings(db, user_id)
    if not ns.email_enabled:
        return None
    user = await db.get(User, user_id)
    recipient = ns.email_to or (user.email if user else "")
    if not recipient:
        return None

    status, error = "pending", None
    if not settings.smtp_configured:
        status, error = "skipped", SMTP_NOT_CONFIGURED
    elif not bypass_cooldown and monitor_id is not None and ns.email_cooldown_minutes > 0:
        recent = await db.scalar(
            select(func.count())
            .select_from(NotificationDelivery)
            .where(
                NotificationDelivery.user_id == user_id,
                NotificationDelivery.monitor_id == monitor_id,
                NotificationDelivery.kind == kind,
                NotificationDelivery.status.in_(("pending", "sent")),
                NotificationDelivery.created_at >= now - timedelta(minutes=ns.email_cooldown_minutes),
            )
        )
        if recent:
            status = "suppressed"
            error = f"중복 알림 제한: 같은 알림을 {ns.email_cooldown_minutes}분 안에 이미 발송했습니다."
    if status == "pending":
        last_hour = await db.scalar(
            select(func.count())
            .select_from(NotificationDelivery)
            .where(
                NotificationDelivery.user_id == user_id,
                NotificationDelivery.status.in_(("pending", "sent")),
                NotificationDelivery.created_at >= now - timedelta(hours=1),
            )
        )
        if (last_hour or 0) >= settings.email_max_per_hour_per_user:
            status = "suppressed"
            error = f"발송 한도 초과: 시간당 최대 {settings.email_max_per_hour_per_user}건까지 발송합니다."

    delivery = NotificationDelivery(
        notification_id=notification_id,
        user_id=user_id,
        monitor_id=monitor_id,
        kind=kind,
        channel="email",
        recipient=recipient,
        status=status,
        attempts=0,
        last_error=error,
        next_attempt_at=now if status == "pending" else None,
        created_at=now,
    )
    db.add(delivery)
    await db.flush()
    return delivery


def email_body(notification: Notification, settings: Settings) -> str:
    footer = f"\n\n대시보드: {settings.public_base_url.rstrip('/')}/\n— UptimeWatch"
    return notification.message + footer


async def send_delivery(
    delivery: NotificationDelivery,
    notification: Notification,
    sender: EmailSender,
    settings: Settings,
    now: datetime,
) -> None:
    """발송을 1회 시도하고 결과를 delivery 에 기록합니다(커밋은 호출자 책임)."""
    delivery.attempts += 1
    try:
        await sender.send(delivery.recipient, notification.title, email_body(notification, settings))
    except EmailNotConfiguredError:
        delivery.status = "skipped"
        delivery.last_error = SMTP_NOT_CONFIGURED
        delivery.next_attempt_at = None
    except EmailSendError as exc:
        delivery.last_error = str(exc)[:500]
        if delivery.attempts >= settings.notification_max_attempts:
            delivery.status = "failed"
            delivery.next_attempt_at = None
        else:
            delay = RETRY_BACKOFF[min(delivery.attempts - 1, len(RETRY_BACKOFF) - 1)]
            delivery.next_attempt_at = now + delay
        logger.warning("이메일 발송 실패 (delivery=%s, attempt=%s): %s", delivery.id, delivery.attempts, exc)
    else:
        delivery.status = "sent"
        delivery.sent_at = now
        delivery.last_error = None
        delivery.next_attempt_at = None


async def process_pending_deliveries(
    sessionmaker: async_sessionmaker[AsyncSession],
    sender: EmailSender,
    settings: Settings,
    limit: int = 20,
) -> int:
    now = datetime.now(UTC)
    async with sessionmaker() as db, db.begin():
        rows = (
            await db.execute(
                select(NotificationDelivery, Notification)
                .join(Notification, Notification.id == NotificationDelivery.notification_id)
                .where(NotificationDelivery.status == "pending", NotificationDelivery.next_attempt_at <= now)
                .order_by(NotificationDelivery.id)
                .limit(limit)
                .with_for_update(skip_locked=True, of=NotificationDelivery)
            )
        ).all()
        for delivery, notification in rows:
            await send_delivery(delivery, notification, sender, settings, datetime.now(UTC))
        return len(rows)
