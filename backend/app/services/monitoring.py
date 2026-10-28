"""검사 결과 저장과 장애 판정(상태 머신).

규칙
- down 결과: 연속 실패 수 증가. 진행 중 장애가 없고 연속 실패가 failure_threshold 이상이면 장애를 연다.
  장애 시작 시각(started_at)은 연속 실패의 '첫 번째' 실패 시각, 판정 시각(detected_at)은 기준 도달 시각.
  기준 미만 실패는 '일시적 실패'로 기록만 하고 장애를 열지 않는다.
- up 결과: 연속 성공 수 증가. 진행 중 장애가 있고 연속 성공이 recovery_threshold 이상이면 장애를 닫는다.
  복구 시각(resolved_at)은 연속 성공의 첫 성공 시각.
- error(측정 불가) 결과: 기록만 하고 연속 실패/성공 카운터와 장애 상태를 바꾸지 않는다.
- 알림은 상태 전이 시 1회만 생성(dedupe_key)되며, 장애 지속 재알림은 설정한 간격으로만 보낸다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import CheckResult, Incident, Monitor
from app.services.checker import CheckOutcome
from app.services.notifications import (
    create_notification,
    format_duration,
    format_local,
    get_notification_settings,
)


@dataclass
class RecordResult:
    check: CheckResult
    incident_opened: Incident | None = None
    incident_resolved: Incident | None = None
    notifications: list[str] = field(default_factory=list)


async def get_open_incident(db: AsyncSession, monitor_id: int) -> Incident | None:
    return await db.scalar(
        select(Incident).where(Incident.monitor_id == monitor_id, Incident.resolved_at.is_(None))
    )


async def record_check(
    db: AsyncSession,
    monitor: Monitor,
    result: CheckOutcome,
    settings: Settings,
    *,
    is_manual: bool = False,
) -> RecordResult:
    """검사 결과를 저장하고 장애 상태를 갱신합니다. 호출자는 monitor 행을 FOR UPDATE 로 잠가야 합니다."""
    now = result.checked_at
    check = CheckResult(
        monitor_id=monitor.id,
        checked_at=now,
        outcome=result.outcome,
        status_code=result.status_code,
        response_time_ms=result.response_time_ms,
        error_type=result.error_type,
        error_message=result.error_message,
        redirect_count=result.redirect_count,
        tls_expires_at=result.tls_expires_at,
        is_manual=is_manual,
    )
    db.add(check)
    record = RecordResult(check=check)

    monitor.last_checked_at = now
    monitor.last_outcome = result.outcome
    monitor.last_status_code = result.status_code
    monitor.last_response_time_ms = result.response_time_ms
    monitor.last_error_type = result.error_type
    monitor.last_error_message = result.error_message
    if result.tls_expires_at is not None:
        monitor.tls_expires_at = result.tls_expires_at
        monitor.tls_checked_at = now

    if result.outcome == "error":
        await db.flush()
        return record

    ns = await get_notification_settings(db, monitor.user_id)
    incident = await get_open_incident(db, monitor.id)

    if result.outcome == "down":
        if monitor.consecutive_failures == 0 or monitor.failure_streak_started_at is None:
            monitor.failure_streak_started_at = now
        monitor.consecutive_failures += 1
        monitor.consecutive_successes = 0
        monitor.success_streak_started_at = None

        if incident is not None:
            incident.failed_checks += 1
            if monitor.status != "down":
                _set_status(monitor, "down", now)
            await _maybe_remind(db, monitor, incident, ns.reminder_interval_minutes, result, settings, record)
        elif monitor.consecutive_failures >= monitor.failure_threshold:
            incident = Incident(
                monitor_id=monitor.id,
                started_at=monitor.failure_streak_started_at,
                detected_at=now,
                cause_type=result.error_type,
                cause_message=result.error_message,
                failed_checks=monitor.consecutive_failures,
            )
            db.add(incident)
            await db.flush()
            _set_status(monitor, "down", now)
            record.incident_opened = incident
            await create_notification(
                db,
                user_id=monitor.user_id,
                monitor_id=monitor.id,
                incident_id=incident.id,
                kind="down",
                title=f"[장애] {monitor.name}",
                message=(
                    f"'{monitor.name}' 장애가 감지되었습니다.\n"
                    f"대상: {monitor.url}\n"
                    f"장애 시작: {format_local(incident.started_at, settings)}\n"
                    f"원인: {result.error_message or '알 수 없음'}\n"
                    f"연속 실패: {monitor.consecutive_failures}회 (기준 {monitor.failure_threshold}회)"
                ),
                dedupe_key=f"incident:{incident.id}:down",
                settings=settings,
                now=now,
            )
            record.notifications.append("down")
    else:  # up
        if monitor.consecutive_successes == 0 or monitor.success_streak_started_at is None:
            monitor.success_streak_started_at = now
        monitor.consecutive_successes += 1
        monitor.consecutive_failures = 0
        monitor.failure_streak_started_at = None

        if incident is not None:
            if monitor.consecutive_successes >= monitor.recovery_threshold:
                incident.resolved_at = monitor.success_streak_started_at
                _set_status(monitor, "up", now)
                record.incident_resolved = incident
                await create_notification(
                    db,
                    user_id=monitor.user_id,
                    monitor_id=monitor.id,
                    incident_id=incident.id,
                    kind="up",
                    title=f"[복구] {monitor.name}",
                    message=(
                        f"'{monitor.name}' 이(가) 복구되었습니다.\n"
                        f"대상: {monitor.url}\n"
                        f"장애 시작: {format_local(incident.started_at, settings)}\n"
                        f"복구 시각: {format_local(incident.resolved_at, settings)}\n"
                        f"장애 지속 시간: {format_duration(incident.duration_seconds)}"
                    ),
                    dedupe_key=f"incident:{incident.id}:up",
                    settings=settings,
                    now=now,
                )
                record.notifications.append("up")
        elif monitor.status != "up":
            _set_status(monitor, "up", now)

    await _maybe_warn_tls(db, monitor, result, ns.tls_warning_days, settings, record)
    await db.flush()
    return record


def _set_status(monitor: Monitor, status: str, now: datetime) -> None:
    if monitor.status != status:
        monitor.status = status
        monitor.status_changed_at = now


async def _maybe_remind(
    db: AsyncSession,
    monitor: Monitor,
    incident: Incident,
    interval_minutes: int,
    result: CheckOutcome,
    settings: Settings,
    record: RecordResult,
) -> None:
    if interval_minutes <= 0:
        return
    now = result.checked_at
    last = incident.last_reminder_at or incident.detected_at
    if now - last < timedelta(minutes=interval_minutes):
        return
    incident.reminder_count += 1
    incident.last_reminder_at = now
    await create_notification(
        db,
        user_id=monitor.user_id,
        monitor_id=monitor.id,
        incident_id=incident.id,
        kind="reminder",
        title=f"[재알림] {monitor.name} 장애 지속 중",
        message=(
            f"'{monitor.name}' 장애가 계속되고 있습니다.\n"
            f"장애 시작: {format_local(incident.started_at, settings)}\n"
            f"경과 시간: {format_duration((now - incident.started_at).total_seconds())}\n"
            f"최근 오류: {result.error_message or '알 수 없음'}"
        ),
        dedupe_key=f"incident:{incident.id}:reminder:{incident.reminder_count}",
        settings=settings,
        now=now,
    )
    record.notifications.append("reminder")


async def _maybe_warn_tls(
    db: AsyncSession,
    monitor: Monitor,
    result: CheckOutcome,
    warning_days: int,
    settings: Settings,
    record: RecordResult,
) -> None:
    expires = result.tls_expires_at
    if expires is None or warning_days <= 0:
        return
    remaining = expires - result.checked_at
    if remaining > timedelta(days=warning_days):
        return
    days_left = max(0, remaining.days)
    notification, _ = await create_notification(
        db,
        user_id=monitor.user_id,
        monitor_id=monitor.id,
        kind="tls_expiring",
        title=f"[인증서] {monitor.name} TLS 인증서 만료 임박 ({days_left}일 남음)",
        message=(
            f"'{monitor.name}' 의 TLS 인증서가 곧 만료됩니다.\n"
            f"만료 시각: {format_local(expires, settings)}\n"
            f"남은 기간: 약 {days_left}일"
        ),
        dedupe_key=f"tls:{monitor.id}:{expires.date().isoformat()}",
        settings=settings,
        now=result.checked_at,
    )
    if notification is not None:
        record.notifications.append("tls_expiring")
