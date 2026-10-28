"""가동률·응답시간 통계.

가동률 정의 (관측 기반)
    uptime = up 검사 수 / (up 검사 수 + down 검사 수)
- 검사 공백(작업자 중단·일시 정지 등)은 분자·분모 어디에도 포함하지 않으며 '정상'으로 간주하지 않습니다.
- 측정 불가(error) 결과도 정상으로 보지 않고 제외합니다.
- 관측값이 하나도 없으면 가동률은 None("데이터 없음")이며 100% 로 표시하지 않습니다.
- 대신 측정 커버리지 = 관측된 검사 수 / 기대 검사 수 를 함께 제공해 공백이 얼마나 되는지 드러냅니다.

응답 시간은 HTTP 응답을 받은 검사(status_code 존재)만 대상으로 합니다(타임아웃 등은 제외).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Monitor

WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
SERIES_STEPS: dict[str, timedelta] = {
    "24h": timedelta(minutes=15),
    "7d": timedelta(hours=2),
    "30d": timedelta(days=1),
}


def uptime_percent(up: int, down: int) -> float | None:
    total = up + down
    if total <= 0:
        return None
    return round(up * 100.0 / total, 3)


def coverage_percent(observed: int, interval_seconds: int, observable_seconds: float) -> float | None:
    if observable_seconds <= 0 or interval_seconds <= 0:
        return None
    expected = max(1.0, observable_seconds / interval_seconds)
    return round(min(1.0, observed / expected) * 100.0, 1)


@dataclass
class WindowStats:
    window: str
    start: datetime
    end: datetime
    up_checks: int
    down_checks: int
    unknown_checks: int
    uptime_pct: float | None
    coverage_pct: float | None
    avg_response_ms: float | None
    max_response_ms: int | None
    min_response_ms: int | None
    p95_response_ms: float | None
    incidents: int
    downtime_seconds: int

    def as_dict(self) -> dict:
        return asdict(self)


_WINDOW_SQL = text(
    """
    SELECT
      count(*) FILTER (WHERE outcome = 'up')    AS up_checks,
      count(*) FILTER (WHERE outcome = 'down')  AS down_checks,
      count(*) FILTER (WHERE outcome = 'error') AS unknown_checks,
      avg(response_time_ms) FILTER (WHERE status_code IS NOT NULL) AS avg_ms,
      max(response_time_ms) FILTER (WHERE status_code IS NOT NULL) AS max_ms,
      min(response_time_ms) FILTER (WHERE status_code IS NOT NULL) AS min_ms,
      percentile_cont(0.95) WITHIN GROUP (ORDER BY response_time_ms)
        FILTER (WHERE status_code IS NOT NULL) AS p95_ms
    FROM check_results
    WHERE monitor_id = :monitor_id AND checked_at >= :start AND checked_at < :end
    """
)

_INCIDENT_SQL = text(
    """
    SELECT
      count(*) FILTER (WHERE started_at >= :start) AS started,
      coalesce(sum(extract(epoch FROM
          least(coalesce(resolved_at, :end), :end) - greatest(started_at, :start)
      )), 0) AS downtime
    FROM incidents
    WHERE monitor_id = :monitor_id
      AND started_at < :end
      AND (resolved_at IS NULL OR resolved_at > :start)
    """
)


async def window_stats(db: AsyncSession, monitor: Monitor, window: str, now: datetime | None = None) -> WindowStats:
    now = now or datetime.now(UTC)
    start = now - WINDOWS[window]
    params = {"monitor_id": monitor.id, "start": start, "end": now}
    row = (await db.execute(_WINDOW_SQL, params)).mappings().one()
    inc = (await db.execute(_INCIDENT_SQL, params)).mappings().one()
    up, down, unknown = int(row["up_checks"]), int(row["down_checks"]), int(row["unknown_checks"])
    observable_start = max(start, monitor.created_at) if monitor.created_at else start
    return WindowStats(
        window=window,
        start=start,
        end=now,
        up_checks=up,
        down_checks=down,
        unknown_checks=unknown,
        uptime_pct=uptime_percent(up, down),
        coverage_pct=coverage_percent(
            up + down, monitor.interval_seconds, (now - observable_start).total_seconds()
        ),
        avg_response_ms=round(float(row["avg_ms"]), 1) if row["avg_ms"] is not None else None,
        max_response_ms=row["max_ms"],
        min_response_ms=row["min_ms"],
        p95_response_ms=round(float(row["p95_ms"]), 1) if row["p95_ms"] is not None else None,
        incidents=int(inc["started"] or 0),
        downtime_seconds=int(float(inc["downtime"] or 0)),
    )


def _origin(tz: str) -> datetime:
    return datetime(2000, 1, 1, tzinfo=ZoneInfo(tz))


def _align(ts: datetime, origin: datetime, step: timedelta) -> datetime:
    n = (ts - origin) // step
    return origin + n * step


_SERIES_SQL = text(
    """
    SELECT
      date_bin(:step, checked_at, :origin) AS bucket,
      avg(response_time_ms) FILTER (WHERE status_code IS NOT NULL) AS avg_ms,
      max(response_time_ms) FILTER (WHERE status_code IS NOT NULL) AS max_ms,
      min(response_time_ms) FILTER (WHERE status_code IS NOT NULL) AS min_ms,
      count(*) FILTER (WHERE outcome = 'up')    AS up,
      count(*) FILTER (WHERE outcome = 'down')  AS down,
      count(*) FILTER (WHERE outcome = 'error') AS unknown
    FROM check_results
    WHERE monitor_id = :monitor_id AND checked_at >= :start AND checked_at < :end
    GROUP BY bucket
    ORDER BY bucket
    """
)


async def response_time_series(
    db: AsyncSession, monitor_id: int, range_key: str, tz: str, now: datetime | None = None
) -> list[dict]:
    """구간별 응답 시간·가동률. 데이터가 없는 구간은 값이 null 인 점으로 반환합니다(0 으로 채우지 않음)."""
    now = now or datetime.now(UTC)
    step = SERIES_STEPS[range_key]
    origin = _origin(tz)
    start = _align(now - WINDOWS[range_key], origin, step) + step
    rows = (
        await db.execute(
            _SERIES_SQL,
            {
                "step": step,
                "origin": origin,
                "monitor_id": monitor_id,
                "start": start,
                "end": now,
            },
        )
    ).mappings()
    by_bucket = {r["bucket"].astimezone(UTC): r for r in rows}
    points: list[dict] = []
    bucket = start
    while bucket <= now:
        r = by_bucket.get(bucket.astimezone(UTC))
        up = int(r["up"]) if r else 0
        down = int(r["down"]) if r else 0
        points.append(
            {
                "t": bucket.astimezone(UTC).isoformat(),
                "avg_ms": round(float(r["avg_ms"]), 1) if r and r["avg_ms"] is not None else None,
                "max_ms": r["max_ms"] if r else None,
                "min_ms": r["min_ms"] if r else None,
                "up": up,
                "down": down,
                "unknown": int(r["unknown"]) if r else 0,
                "uptime_pct": uptime_percent(up, down),
            }
        )
        bucket += step
    return points


_DAILY_SQL = text(
    """
    SELECT
      (date_trunc('day', checked_at AT TIME ZONE :tz))::date AS day,
      count(*) FILTER (WHERE outcome = 'up')    AS up,
      count(*) FILTER (WHERE outcome = 'down')  AS down,
      count(*) FILTER (WHERE outcome = 'error') AS unknown,
      avg(response_time_ms) FILTER (WHERE status_code IS NOT NULL) AS avg_ms
    FROM check_results
    WHERE monitor_id = :monitor_id AND checked_at >= :start
    GROUP BY day
    """
)

_DAILY_INCIDENTS_SQL = text(
    """
    SELECT (date_trunc('day', started_at AT TIME ZONE :tz))::date AS day, count(*) AS n
    FROM incidents WHERE monitor_id = :monitor_id AND started_at >= :start
    GROUP BY day
    """
)


async def daily_uptime(
    db: AsyncSession, monitor_id: int, days: int, tz: str, now: datetime | None = None
) -> list[dict]:
    now = now or datetime.now(UTC)
    zone = ZoneInfo(tz)
    today: date = now.astimezone(zone).date()
    first_day = today - timedelta(days=days - 1)
    start = datetime.combine(first_day, datetime.min.time(), tzinfo=zone)
    params = {"tz": tz, "monitor_id": monitor_id, "start": start}
    rows = {r["day"]: r for r in (await db.execute(_DAILY_SQL, params)).mappings()}
    incidents = {r["day"]: int(r["n"]) for r in (await db.execute(_DAILY_INCIDENTS_SQL, params)).mappings()}
    result = []
    for i in range(days):
        d = first_day + timedelta(days=i)
        r = rows.get(d)
        up = int(r["up"]) if r else 0
        down = int(r["down"]) if r else 0
        result.append(
            {
                "date": d.isoformat(),
                "up": up,
                "down": down,
                "unknown": int(r["unknown"]) if r else 0,
                "uptime_pct": uptime_percent(up, down),
                "avg_ms": round(float(r["avg_ms"]), 1) if r and r["avg_ms"] is not None else None,
                "incidents": incidents.get(d, 0),
            }
        )
    return result


async def uptime_for_monitors(
    db: AsyncSession, monitor_ids: list[int], window: timedelta, now: datetime | None = None
) -> dict[int, dict]:
    if not monitor_ids:
        return {}
    now = now or datetime.now(UTC)
    rows = (
        await db.execute(
            text(
                """
                SELECT monitor_id,
                  count(*) FILTER (WHERE outcome = 'up') AS up,
                  count(*) FILTER (WHERE outcome = 'down') AS down,
                  avg(response_time_ms) FILTER (WHERE status_code IS NOT NULL) AS avg_ms
                FROM check_results
                WHERE monitor_id = ANY(:ids) AND checked_at >= :start
                GROUP BY monitor_id
                """
            ),
            {"ids": monitor_ids, "start": now - window},
        )
    ).mappings()
    out = {mid: {"uptime_pct": None, "avg_ms": None, "checks": 0} for mid in monitor_ids}
    for r in rows:
        out[r["monitor_id"]] = {
            "uptime_pct": uptime_percent(int(r["up"]), int(r["down"])),
            "avg_ms": round(float(r["avg_ms"]), 1) if r["avg_ms"] is not None else None,
            "checks": int(r["up"]) + int(r["down"]),
        }
    return out
