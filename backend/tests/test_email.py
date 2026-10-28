"""이메일 발송: 로컬 모의 SMTP 서버(aiosmtpd)로 성공·실패·재시도 기록을 검증."""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta

import pytest
from aiosmtpd.controller import Controller
from sqlalchemy import select, update

from app.models import NotificationDelivery
from app.services.email import EmailSender
from app.services.notifications import create_notification, process_pending_deliveries
from tests.helpers import make_user


class _Collector:
    def __init__(self) -> None:
        self.messages: list[tuple[str, list[str], str]] = []

    async def handle_DATA(self, server, session, envelope):  # noqa: N802
        self.messages.append((envelope.mail_from, envelope.rcpt_tos, envelope.content.decode("utf8", "replace")))
        return "250 OK"


@pytest.fixture
def smtp_server():
    handler = _Collector()
    controller = Controller(handler, hostname="127.0.0.1", port=_free_port())
    controller.start()
    yield controller, handler
    controller.stop()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _queue(sessionmaker, settings, email="ops@example.com") -> int:
    async with sessionmaker() as db:
        user = await make_user(db, email)
        _, delivery = await create_notification(
            db, user_id=user.id, kind="down", title="[장애] 테스트 사이트", message="장애 본문",
            settings=settings, now=datetime.now(UTC), monitor_id=None, dedupe_key="incident:1:down",
        )
        await db.commit()
        assert delivery is not None and delivery.status == "pending"
        return delivery.id


async def test_email_sent_via_smtp(sessionmaker, test_settings, smtp_server) -> None:
    controller, handler = smtp_server
    settings = test_settings.model_copy(update={
        "smtp_host": "127.0.0.1", "smtp_port": controller.port, "smtp_from": "UptimeWatch <uw@example.com>",
        "smtp_starttls": False,
    })
    delivery_id = await _queue(sessionmaker, settings)
    assert await process_pending_deliveries(sessionmaker, EmailSender(settings), settings) == 1
    async with sessionmaker() as db:
        d = await db.get(NotificationDelivery, delivery_id)
        assert d.status == "sent" and d.attempts == 1 and d.sent_at is not None
    assert len(handler.messages) == 1
    _from, rcpt, content = handler.messages[0]
    assert rcpt == ["ops@example.com"]
    assert "Subject:" in content


async def test_email_failure_is_retried_then_recorded(sessionmaker, test_settings) -> None:
    settings = test_settings.model_copy(update={
        "smtp_host": "127.0.0.1", "smtp_port": _free_port(), "smtp_from": "uw@example.com",
        "smtp_starttls": False, "smtp_timeout_seconds": 2, "notification_max_attempts": 3,
    })
    delivery_id = await _queue(sessionmaker, settings)
    sender = EmailSender(settings)
    for attempt in range(1, 4):
        assert await process_pending_deliveries(sessionmaker, sender, settings) == 1
        async with sessionmaker() as db:
            d = await db.get(NotificationDelivery, delivery_id)
            assert d.attempts == attempt and d.last_error
            if attempt < 3:
                assert d.status == "pending" and d.next_attempt_at > datetime.now(UTC)
                # 재시도 시각까지 기다린 것으로 처리
                await db.execute(update(NotificationDelivery).values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1)))
                await db.commit()
            else:
                assert d.status == "failed" and d.next_attempt_at is None
    assert await process_pending_deliveries(sessionmaker, sender, settings) == 0


async def test_failed_delivery_listed_via_api(register, sessionmaker) -> None:
    user = await register()
    async with sessionmaker() as db:
        from app.models import Notification

        n = Notification(user_id=user.user_id, kind="down", title="t", message="m", created_at=datetime.now(UTC))
        db.add(n)
        await db.flush()
        db.add(NotificationDelivery(notification_id=n.id, user_id=user.user_id, kind="down", channel="email",
                                    recipient=user.email, status="failed", attempts=3, last_error="SMTPConnectError: refused"))
        await db.commit()
    rows = (await user.get("/api/notifications/deliveries?status=failed")).json()
    assert len(rows) == 1 and rows[0]["last_error"].startswith("SMTPConnectError")
    async with sessionmaker() as db:
        assert (await db.scalars(select(NotificationDelivery))).all()
