"""상태 페이지: 관리자 API(/api/status-pages)와 공개 API(/api/public/status/{slug}) 분리.

공개 응답은 허용 목록 방식으로 직접 구성합니다. URL·IP·오류 메시지·상태 코드·내부 모니터 ID·
임계값·TLS 정보 등 내부 정보는 포함하지 않습니다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, enforce, public_limiter
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Incident, Monitor, StatusPage, StatusPageMonitor, User
from app.schemas import StatusPageIn, StatusPageItemOut, StatusPageOut
from app.security.auth import get_current_user
from app.services import stats

router = APIRouter(prefix="/api/status-pages", tags=["status-pages"])
public_router = APIRouter(prefix="/api/public", tags=["public"])


def _out(page: StatusPage) -> StatusPageOut:
    return StatusPageOut(
        id=page.id,
        slug=page.slug,
        title=page.title,
        description=page.description,
        is_published=page.is_published,
        show_uptime=page.show_uptime,
        show_response_times=page.show_response_times,
        show_incidents=page.show_incidents,
        items=[
            StatusPageItemOut(monitor_id=i.monitor_id, display_name=i.display_name, sort_order=i.sort_order)
            for i in page.items
        ],
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


async def _owned_page(page_id: int, user: User, db: AsyncSession) -> StatusPage:
    page = await db.scalar(select(StatusPage).where(StatusPage.id == page_id, StatusPage.user_id == user.id))
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "상태 페이지를 찾을 수 없습니다.")
    return page


async def _apply(page: StatusPage, body: StatusPageIn, user: User, db: AsyncSession) -> None:
    with db.no_autoflush:
        clash = await db.scalar(
            select(StatusPage.id).where(StatusPage.slug == body.slug, StatusPage.id != (page.id or 0))
        )
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 사용 중인 주소(slug)입니다.")
    monitor_ids = [i.monitor_id for i in body.items]
    if len(set(monitor_ids)) != len(monitor_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "같은 모니터를 두 번 추가할 수 없습니다.")
    if monitor_ids:
        owned = set(
            (await db.scalars(select(Monitor.id).where(Monitor.id.in_(monitor_ids), Monitor.user_id == user.id))).all()
        )
        if owned != set(monitor_ids):
            # 다른 사용자의 모니터 ID 를 넣는 시도 차단
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "본인 모니터만 상태 페이지에 추가할 수 있습니다.")
    page.slug = body.slug
    page.title = body.title.strip()
    page.description = body.description.strip()
    page.is_published = body.is_published
    page.show_uptime = body.show_uptime
    page.show_response_times = body.show_response_times
    page.show_incidents = body.show_incidents
    page.items.clear()
    await db.flush()
    for order, item in enumerate(body.items):
        page.items.append(
            StatusPageMonitor(monitor_id=item.monitor_id, display_name=item.display_name.strip(), sort_order=order)
        )


@router.get("", response_model=list[StatusPageOut])
async def list_pages(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[StatusPageOut]:
    pages = (await db.scalars(select(StatusPage).where(StatusPage.user_id == user.id).order_by(StatusPage.id))).all()
    return [_out(p) for p in pages]


@router.post("", response_model=StatusPageOut, status_code=status.HTTP_201_CREATED)
async def create_page(
    body: StatusPageIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> StatusPageOut:
    page = StatusPage(user_id=user.id, slug=body.slug, title=body.title, items=[])
    await _apply(page, body, user, db)
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return _out(page)


@router.get("/{page_id}", response_model=StatusPageOut)
async def get_page(
    page_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> StatusPageOut:
    return _out(await _owned_page(page_id, user, db))


@router.put("/{page_id}", response_model=StatusPageOut)
async def update_page(
    page_id: int, body: StatusPageIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> StatusPageOut:
    page = await _owned_page(page_id, user, db)
    await _apply(page, body, user, db)
    await db.commit()
    await db.refresh(page)
    return _out(page)


@router.delete("/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_page(
    page_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Response:
    page = await _owned_page(page_id, user, db)
    await db.delete(page)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _public_status(monitor: Monitor) -> str:
    if not monitor.is_active:
        return "paused"
    if monitor.status in ("up", "down"):
        return monitor.status
    return "unknown"


@public_router.get("/status/{slug}")
async def public_status_page(
    slug: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    enforce(public_limiter(), client_ip(request), "요청이 너무 많습니다. 잠시 후 다시 시도하세요.")
    page = await db.scalar(select(StatusPage).where(StatusPage.slug == slug.lower(), StatusPage.is_published.is_(True)))
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "상태 페이지를 찾을 수 없습니다.")

    now = datetime.now(UTC)
    monitor_ids = [i.monitor_id for i in page.items]
    monitors = {
        m.id: m for m in (await db.scalars(select(Monitor).where(Monitor.id.in_(monitor_ids)))).all()
    } if monitor_ids else {}

    components = []
    names: dict[int, str] = {}
    for idx, item in enumerate(page.items):
        monitor = monitors.get(item.monitor_id)
        if monitor is None:
            continue
        names[monitor.id] = item.display_name
        component: dict = {
            "key": f"c{idx}",
            "name": item.display_name,
            "status": _public_status(monitor),
            "last_checked_at": monitor.last_checked_at,
        }
        if page.show_uptime:
            windows = {}
            for w in ("24h", "7d", "30d"):
                ws = await stats.window_stats(db, monitor, w, now)
                windows[w] = ws.uptime_pct
            component["uptime"] = windows
            component["daily"] = [
                {"date": d["date"], "uptime_pct": d["uptime_pct"], "incidents": d["incidents"]}
                for d in await stats.daily_uptime(db, monitor.id, 90, settings.display_timezone, now)
            ]
        if page.show_response_times:
            component["response_times"] = [
                {"t": p["t"], "avg_ms": p["avg_ms"]}
                for p in await stats.response_time_series(db, monitor.id, "24h", settings.display_timezone, now)
            ]
        components.append(component)

    statuses = [c["status"] for c in components]
    if not statuses or all(s in ("unknown", "paused") for s in statuses):
        overall = "unknown"
    elif all(s != "down" for s in statuses):
        overall = "operational"
    elif all(s == "down" for s in statuses if s not in ("unknown", "paused")):
        overall = "major_outage"
    else:
        overall = "partial_outage"

    incidents: list[dict] = []
    if page.show_incidents and names:
        rows = (
            await db.scalars(
                select(Incident)
                .where(Incident.monitor_id.in_(list(names)), Incident.started_at >= now - timedelta(days=30))
                .order_by(Incident.started_at.desc())
                .limit(20)
            )
        ).all()
        incidents = [
            {
                "component": names[i.monitor_id],
                "started_at": i.started_at,
                "resolved_at": i.resolved_at,
                "duration_seconds": i.duration_seconds,
                "ongoing": i.resolved_at is None,
            }
            for i in rows
        ]

    response.headers["Cache-Control"] = "public, max-age=30"
    return {
        "title": page.title,
        "description": page.description,
        "overall": overall,
        "generated_at": now,
        "show_uptime": page.show_uptime,
        "show_response_times": page.show_response_times,
        "show_incidents": page.show_incidents,
        "components": components,
        "incidents": incidents,
    }
