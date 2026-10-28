"""대시보드 요약과 사용자 전체 장애 목록."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.monitors import incident_out
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Incident, Monitor, Notification, User, WorkerHeartbeat
from app.schemas import IncidentOut
from app.security.auth import get_current_user
from app.services.stats import uptime_percent

router = APIRouter(prefix="/api", tags=["overview"])


async def worker_status(db: AsyncSession, settings: Settings) -> dict:
    last_seen = await db.scalar(select(func.max(WorkerHeartbeat.last_seen_at)))
    if last_seen is None:
        return {"status": "never", "last_seen_at": None}
    stale = datetime.now(UTC) - last_seen > timedelta(seconds=settings.worker_stale_after_seconds)
    return {"status": "stale" if stale else "ok", "last_seen_at": last_seen}


@router.get("/dashboard")
async def dashboard(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    counts = {"total": 0, "up": 0, "down": 0, "paused": 0, "pending": 0}
    for status_, n in (
        await db.execute(
            select(Monitor.status, func.count()).where(Monitor.user_id == user.id).group_by(Monitor.status)
        )
    ).all():
        counts[status_] = counts.get(status_, 0) + n
        counts["total"] += n

    agg = (
        await db.execute(
            text(
                """
                SELECT count(*) FILTER (WHERE c.outcome = 'up') AS up,
                       count(*) FILTER (WHERE c.outcome = 'down') AS down,
                       avg(c.response_time_ms) FILTER (WHERE c.status_code IS NOT NULL) AS avg_ms
                FROM check_results c JOIN monitors m ON m.id = c.monitor_id
                WHERE m.user_id = :uid AND c.checked_at >= :start
                """
            ),
            {"uid": user.id, "start": datetime.now(UTC) - timedelta(hours=24)},
        )
    ).mappings().one()

    open_rows = (
        await db.execute(
            select(Incident, Monitor.name)
            .join(Monitor, Monitor.id == Incident.monitor_id)
            .where(Monitor.user_id == user.id, Incident.resolved_at.is_(None))
            .order_by(Incident.started_at.desc())
        )
    ).all()
    incidents_24h = await db.scalar(
        select(func.count())
        .select_from(Incident)
        .join(Monitor, Monitor.id == Incident.monitor_id)
        .where(Monitor.user_id == user.id, Incident.started_at >= datetime.now(UTC) - timedelta(hours=24))
    )
    unread = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return {
        "counts": counts,
        "uptime_24h": uptime_percent(int(agg["up"]), int(agg["down"])),
        "avg_response_24h": round(float(agg["avg_ms"]), 1) if agg["avg_ms"] is not None else None,
        "incidents_24h": incidents_24h or 0,
        "open_incidents": [incident_out(i, name).model_dump(mode="json") for i, name in open_rows],
        "unread_notifications": unread or 0,
        "worker": await worker_status(db, settings),
        "email": {"configured": settings.smtp_configured},
    }


@router.get("/incidents", response_model=list[IncidentOut])
async def list_incidents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    state: Literal["all", "ongoing", "resolved"] = "all",
    monitor_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[IncidentOut]:
    stmt = (
        select(Incident, Monitor.name)
        .join(Monitor, Monitor.id == Incident.monitor_id)
        .where(Monitor.user_id == user.id)
    )
    if state == "ongoing":
        stmt = stmt.where(Incident.resolved_at.is_(None))
    elif state == "resolved":
        stmt = stmt.where(Incident.resolved_at.is_not(None))
    if monitor_id is not None:
        stmt = stmt.where(Incident.monitor_id == monitor_id)
    rows = (await db.execute(stmt.order_by(Incident.started_at.desc()).limit(limit))).all()
    return [incident_out(i, name) for i, name in rows]
