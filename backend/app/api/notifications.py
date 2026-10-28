from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import enforce, test_notification_limiter
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Notification, NotificationDelivery, NotificationSettings, User
from app.schemas import DeliveryOut, NotificationOut, NotificationSettingsIn, NotificationSettingsOut
from app.security.auth import get_current_user
from app.services.email import EmailSender
from app.services.notifications import create_notification, get_notification_settings, send_delivery

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def get_email_sender(settings: Settings = Depends(get_settings)) -> EmailSender:
    return EmailSender(settings)


def _mask_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return value
    local, domain = value.rsplit("@", 1)
    return f"{local[:2]}{'*' * max(1, len(local) - 2)}@{domain}"


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    return list((await db.scalars(stmt)).all())


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Notification:
    n = await db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "알림을 찾을 수 없습니다.")
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(n)
    return n


@router.post("/read-all")
async def mark_all_read(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
    return {"updated": result.rowcount}


@router.get("/deliveries", response_model=list[DeliveryOut])
async def list_deliveries(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status_filter: Literal["pending", "sent", "failed", "skipped", "suppressed"] | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
) -> list[NotificationDelivery]:
    stmt = select(NotificationDelivery).where(NotificationDelivery.user_id == user.id)
    if status_filter:
        stmt = stmt.where(NotificationDelivery.status == status_filter)
    return list((await db.scalars(stmt.order_by(NotificationDelivery.id.desc()).limit(limit))).all())


@router.get("/channels")
async def channels(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    ns = await get_notification_settings(db, user.id)
    return {
        "dashboard": {"configured": True},
        "email": {
            "configured": settings.smtp_configured,
            "status": "connected" if settings.smtp_configured else "not_configured",
            "from": _mask_email(settings.smtp_from) if settings.smtp_configured else None,
            "enabled": ns.email_enabled,
            "recipient": ns.email_to or user.email,
            "required_env": ["SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"],
        },
    }


@router.get("/settings", response_model=NotificationSettingsOut)
async def get_settings_endpoint(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> NotificationSettingsOut:
    ns = await get_notification_settings(db, user.id)
    return NotificationSettingsOut(
        email_enabled=ns.email_enabled,
        email_to=ns.email_to,
        email_cooldown_minutes=ns.email_cooldown_minutes,
        reminder_interval_minutes=ns.reminder_interval_minutes,
        tls_warning_days=ns.tls_warning_days,
    )


@router.put("/settings", response_model=NotificationSettingsOut)
async def put_settings(
    body: NotificationSettingsIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> NotificationSettingsOut:
    ns = await db.get(NotificationSettings, user.id)
    if ns is None:
        ns = NotificationSettings(user_id=user.id)
        db.add(ns)
    ns.email_enabled = body.email_enabled
    ns.email_to = str(body.email_to).lower() if body.email_to else None
    ns.email_cooldown_minutes = body.email_cooldown_minutes
    ns.reminder_interval_minutes = body.reminder_interval_minutes
    ns.tls_warning_days = body.tls_warning_days
    await db.commit()
    return NotificationSettingsOut(**body.model_dump(exclude={"email_to"}), email_to=ns.email_to)


@router.post("/test")
async def send_test_notification(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    sender: EmailSender = Depends(get_email_sender),
) -> dict:
    """대시보드 알림을 만들고, 이메일이 연동되어 있으면 즉시 1회 발송을 시도합니다."""
    enforce(
        test_notification_limiter(),
        f"user:{user.id}",
        f"테스트 알림은 {settings.test_notification_cooldown_seconds}초에 한 번만 보낼 수 있습니다.",
    )
    now = datetime.now(UTC)
    notification, delivery = await create_notification(
        db,
        user_id=user.id,
        kind="test",
        title="[테스트] UptimeWatch 알림 테스트",
        message="UptimeWatch 테스트 알림입니다. 이 알림이 보이면 알림 설정이 정상입니다.",
        settings=settings,
        now=now,
        bypass_cooldown=True,
    )
    assert notification is not None
    email_result: dict = {"status": "disabled", "error": None}
    if delivery is not None:
        if delivery.status == "pending":
            await send_delivery(delivery, notification, sender, settings, datetime.now(UTC))
            if delivery.status == "pending":
                # 테스트 알림은 재시도하지 않고 즉시 실패로 기록해 결과를 바로 보여줍니다.
                delivery.status = "failed"
                delivery.next_attempt_at = None
        email_result = {"status": delivery.status, "error": delivery.last_error, "recipient": delivery.recipient}
    await db.commit()
    return {"dashboard": {"status": "created", "notification_id": notification.id}, "email": email_result}
