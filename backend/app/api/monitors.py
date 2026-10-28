from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_resolver
from app.config import Settings, get_settings
from app.db import get_db
from app.models import CheckResult, Incident, Monitor, User
from app.schemas import CheckOut, IncidentOut, MonitorCreate, MonitorListItem, MonitorOut, MonitorUpdate
from app.security.auth import get_current_user
from app.security.ssrf import (
    AddressPolicy,
    DNSResolutionError,
    Resolver,
    SSRFError,
    resolve_and_validate,
    validate_url,
)
from app.services import stats

router = APIRouter(prefix="/api/monitors", tags=["monitors"])


def _now() -> datetime:
    return datetime.now(UTC)


async def get_owned_monitor(
    monitor_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    """소유자의 모니터만 반환합니다. 다른 사용자의 모니터는 존재 여부도 드러내지 않도록 404."""
    monitor = await db.scalar(select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id))
    if monitor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "모니터를 찾을 수 없습니다.")
    return monitor


async def validate_target_url(url: str, settings: Settings, resolver: Resolver) -> str:
    policy = AddressPolicy.from_settings(settings.allowed_ports, settings.allowed_cidrs)
    try:
        validated = validate_url(url, policy)
    except SSRFError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.message) from exc
    if validated.ip_literal is None:
        try:
            async with asyncio.timeout(5):
                await resolve_and_validate(validated.host, validated.port, policy, resolver)
        except SSRFError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.message) from exc
        except (DNSResolutionError, TimeoutError):
            # 아직 DNS 가 없더라도 등록은 허용합니다. 검사 시점마다 다시 검증하며 'DNS 오류'로 기록됩니다.
            pass
    return validated.url


def _validate_timing(interval: int, timeout: int, settings: Settings) -> None:
    if not settings.check_min_interval_seconds <= interval <= settings.check_max_interval_seconds:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"확인 주기는 {settings.check_min_interval_seconds}초 이상 "
            f"{settings.check_max_interval_seconds}초 이하로 설정하세요.",
        )
    if not settings.check_min_timeout_seconds <= timeout <= settings.check_max_timeout_seconds:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"타임아웃은 {settings.check_min_timeout_seconds}~{settings.check_max_timeout_seconds}초로 설정하세요.",
        )
    if timeout >= interval:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "타임아웃은 확인 주기보다 짧아야 합니다.")


async def _open_incidents(db: AsyncSession, monitor_ids: list[int]) -> dict[int, int]:
    if not monitor_ids:
        return {}
    rows = await db.execute(
        select(Incident.monitor_id, Incident.id).where(
            Incident.monitor_id.in_(monitor_ids), Incident.resolved_at.is_(None)
        )
    )
    return {mid: iid for mid, iid in rows.all()}


@router.get("", response_model=list[MonitorListItem])
async def list_monitors(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[MonitorListItem]:
    monitors = (
        await db.scalars(select(Monitor).where(Monitor.user_id == user.id).order_by(Monitor.name, Monitor.id))
    ).all()
    ids = [m.id for m in monitors]
    uptimes = await stats.uptime_for_monitors(db, ids, timedelta(hours=24))
    open_incidents = await _open_incidents(db, ids)
    items = []
    for m in monitors:
        item = MonitorListItem.model_validate(m)
        item.uptime_24h = uptimes[m.id]["uptime_pct"]
        item.avg_response_24h = uptimes[m.id]["avg_ms"]
        item.open_incident_id = open_incidents.get(m.id)
        items.append(item)
    return items


@router.post("", response_model=MonitorOut, status_code=status.HTTP_201_CREATED)
async def create_monitor(
    body: MonitorCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    resolver: Resolver = Depends(get_resolver),
) -> Monitor:
    count = await db.scalar(select(func.count()).select_from(Monitor).where(Monitor.user_id == user.id))
    if (count or 0) >= settings.max_monitors_per_user:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"모니터는 사용자당 최대 {settings.max_monitors_per_user}개까지 등록할 수 있습니다.",
        )
    _validate_timing(body.interval_seconds, body.timeout_seconds, settings)
    url = await validate_target_url(body.url, settings, resolver)
    now = _now()
    monitor = Monitor(
        user_id=user.id,
        name=body.name,
        description=body.description.strip(),
        url=url,
        method=body.method,
        interval_seconds=body.interval_seconds,
        timeout_seconds=body.timeout_seconds,
        expected_status=body.expected_status,
        failure_threshold=body.failure_threshold,
        recovery_threshold=body.recovery_threshold,
        follow_redirects=body.follow_redirects,
        is_active=body.is_active,
        status="pending" if body.is_active else "paused",
        status_changed_at=now,
        consecutive_failures=0,
        consecutive_successes=0,
        next_check_at=now if body.is_active else None,
    )
    db.add(monitor)
    await db.commit()
    await db.refresh(monitor)
    return monitor


@router.get("/{monitor_id}", response_model=MonitorListItem)
async def get_monitor(
    monitor: Monitor = Depends(get_owned_monitor), db: AsyncSession = Depends(get_db)
) -> MonitorListItem:
    uptimes = await stats.uptime_for_monitors(db, [monitor.id], timedelta(hours=24))
    item = MonitorListItem.model_validate(monitor)
    item.uptime_24h = uptimes[monitor.id]["uptime_pct"]
    item.avg_response_24h = uptimes[monitor.id]["avg_ms"]
    item.open_incident_id = (await _open_incidents(db, [monitor.id])).get(monitor.id)
    return item


@router.patch("/{monitor_id}", response_model=MonitorOut)
async def update_monitor(
    body: MonitorUpdate,
    monitor: Monitor = Depends(get_owned_monitor),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    resolver: Resolver = Depends(get_resolver),
) -> Monitor:
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    interval = data.get("interval_seconds", monitor.interval_seconds)
    timeout = data.get("timeout_seconds", monitor.timeout_seconds)
    _validate_timing(interval, timeout, settings)
    if "url" in data:
        new_url = await validate_target_url(data["url"], settings, resolver)
        if new_url != monitor.url:
            # 대상이 바뀌면 연속 카운터·인증서 정보를 초기화합니다(이전 기록은 보존).
            monitor.url = new_url
            monitor.consecutive_failures = 0
            monitor.consecutive_successes = 0
            monitor.failure_streak_started_at = None
            monitor.success_streak_started_at = None
            monitor.tls_expires_at = None
            monitor.tls_checked_at = None
            if monitor.is_active:
                monitor.next_check_at = _now()
        data.pop("url")
    if "name" in data:
        data["name"] = data["name"].strip()
    if "description" in data:
        data["description"] = data["description"].strip()
    for key, value in data.items():
        setattr(monitor, key, value)
    if monitor.is_active and monitor.next_check_at is not None:
        soonest = _now() + timedelta(seconds=monitor.interval_seconds)
        if monitor.next_check_at > soonest:
            monitor.next_check_at = soonest
    await db.commit()
    await db.refresh(monitor)
    return monitor


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitor(
    monitor: Monitor = Depends(get_owned_monitor), db: AsyncSession = Depends(get_db)
) -> Response:
    await db.delete(monitor)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{monitor_id}/pause", response_model=MonitorOut)
async def pause_monitor(monitor: Monitor = Depends(get_owned_monitor), db: AsyncSession = Depends(get_db)) -> Monitor:
    if monitor.is_active:
        monitor.is_active = False
        monitor.status = "paused"
        monitor.status_changed_at = _now()
        monitor.next_check_at = None
        monitor.manual_check_requested_at = None
        await db.commit()
        await db.refresh(monitor)
    return monitor


@router.post("/{monitor_id}/resume", response_model=MonitorOut)
async def resume_monitor(
    monitor: Monitor = Depends(get_owned_monitor), db: AsyncSession = Depends(get_db)
) -> Monitor:
    if not monitor.is_active:
        has_open = (await _open_incidents(db, [monitor.id])).get(monitor.id)
        now = _now()
        monitor.is_active = True
        monitor.status = "down" if has_open else "pending"
        monitor.status_changed_at = now
        # 일시 정지 전의 연속 카운터가 정지 기간을 건너 이어지지 않도록 초기화
        monitor.consecutive_failures = 0
        monitor.consecutive_successes = 0
        monitor.failure_streak_started_at = None
        monitor.success_streak_started_at = None
        monitor.next_check_at = now
        await db.commit()
        await db.refresh(monitor)
    return monitor


@router.post("/{monitor_id}/check", status_code=status.HTTP_202_ACCEPTED)
async def request_check(
    monitor: Monitor = Depends(get_owned_monitor),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """즉시 검사를 예약합니다. 실제 요청은 작업자가 수행합니다(빈도 제한 적용)."""
    if not monitor.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "일시 정지된 모니터는 검사할 수 없습니다. 먼저 재개하세요.")
    now = _now()
    cooldown = timedelta(seconds=settings.manual_check_cooldown_seconds)
    last = monitor.manual_check_requested_at or (
        monitor.last_checked_at if monitor.last_checked_at and monitor.last_checked_at > now - cooldown else None
    )
    if last is not None and now - last < cooldown:
        wait = int((cooldown - (now - last)).total_seconds()) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"방금 검사했습니다. {wait}초 후 다시 시도하세요.",
            headers={"Retry-After": str(wait)},
        )
    monitor.manual_check_requested_at = now
    monitor.next_check_at = now
    await db.commit()
    return {"queued": True, "requested_at": now.isoformat()}


@router.get("/{monitor_id}/checks", response_model=list[CheckOut])
async def list_checks(
    monitor: Monitor = Depends(get_owned_monitor),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    outcome: Literal["up", "down", "error"] | None = None,
) -> list[CheckResult]:
    stmt = select(CheckResult).where(CheckResult.monitor_id == monitor.id)
    if outcome:
        stmt = stmt.where(CheckResult.outcome == outcome)
    return list((await db.scalars(stmt.order_by(CheckResult.checked_at.desc()).limit(limit))).all())


@router.get("/{monitor_id}/stats")
async def monitor_stats(monitor: Monitor = Depends(get_owned_monitor), db: AsyncSession = Depends(get_db)) -> dict:
    now = _now()
    return {w: (await stats.window_stats(db, monitor, w, now)).as_dict() for w in stats.WINDOWS}


@router.get("/{monitor_id}/response-times")
async def monitor_response_times(
    monitor: Monitor = Depends(get_owned_monitor),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    range: Literal["24h", "7d", "30d"] = "24h",  # noqa: A002
) -> dict:
    points = await stats.response_time_series(db, monitor.id, range, settings.display_timezone)
    return {"range": range, "points": points}


@router.get("/{monitor_id}/daily-uptime")
async def monitor_daily_uptime(
    monitor: Monitor = Depends(get_owned_monitor),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    days: int = Query(30, ge=1, le=90),
) -> dict:
    return {"days": await stats.daily_uptime(db, monitor.id, days, settings.display_timezone)}


@router.get("/{monitor_id}/incidents", response_model=list[IncidentOut])
async def monitor_incidents(
    monitor: Monitor = Depends(get_owned_monitor),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[IncidentOut]:
    rows = (
        await db.scalars(
            select(Incident)
            .where(Incident.monitor_id == monitor.id)
            .order_by(Incident.started_at.desc())
            .limit(limit)
        )
    ).all()
    return [incident_out(i, monitor.name) for i in rows]


def incident_out(incident: Incident, monitor_name: str) -> IncidentOut:
    now = _now()
    return IncidentOut(
        id=incident.id,
        monitor_id=incident.monitor_id,
        monitor_name=monitor_name,
        started_at=incident.started_at,
        detected_at=incident.detected_at,
        resolved_at=incident.resolved_at,
        duration_seconds=incident.duration_seconds,
        ongoing_seconds=None
        if incident.resolved_at
        else max(0, int((now - incident.started_at).total_seconds())),
        cause_type=incident.cause_type,
        cause_message=incident.cause_message,
        failed_checks=incident.failed_checks,
    )
