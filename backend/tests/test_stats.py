"""가동률 계산 검증: 관측 기반, 공백·측정 불가를 정상으로 간주하지 않음."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import CheckResult, Incident
from app.services.stats import (
    coverage_percent,
    daily_uptime,
    response_time_series,
    uptime_percent,
    window_stats,
)
from tests.helpers import T0, make_monitor, make_user

NOW = T0 + timedelta(days=1)
M = timedelta(minutes=1)


def test_uptime_percent_basic() -> None:
    assert uptime_percent(90, 10) == 90.0
    assert uptime_percent(1, 2) == pytest.approx(33.333, abs=0.001)
    assert uptime_percent(100, 0) == 100.0
    assert uptime_percent(0, 5) == 0.0


def test_uptime_without_observations_is_unknown_not_100() -> None:
    assert uptime_percent(0, 0) is None


def test_coverage_percent() -> None:
    assert coverage_percent(1440, 60, 86400) == 100.0
    assert coverage_percent(720, 60, 86400) == 50.0
    assert coverage_percent(0, 60, 86400) == 0.0
    assert coverage_percent(2000, 60, 86400) == 100.0  # 수동 검사 등으로 초과해도 100% 상한


def _check(monitor_id: int, at, outcome: str, ms: int | None = 100, status: int | None = 200) -> CheckResult:
    return CheckResult(
        monitor_id=monitor_id,
        checked_at=at,
        outcome=outcome,
        status_code=status if outcome != "error" else None,
        response_time_ms=ms,
        redirect_count=0,
        is_manual=False,
    )


async def test_window_stats_counts_only_observed_checks(sessionmaker) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user, interval_seconds=60)
        start = NOW - timedelta(hours=24)
        # 처음 6시간: 매분 정상 360회
        for i in range(360):
            db.add(_check(monitor.id, start + i * M + timedelta(seconds=1), "up", ms=100 + (i % 10)))
        # 다음 6시간: 검사 공백(작업자 중단) — 아무 기록 없음
        # 이후 40회 실패(타임아웃: 응답 없음) + 측정 불가 20회
        base = start + timedelta(hours=12)
        for i in range(40):
            db.add(_check(monitor.id, base + i * M, "down", ms=10_000, status=None))
        for i in range(20):
            db.add(_check(monitor.id, base + timedelta(hours=1) + i * M, "error", ms=None))
        await db.commit()

        s = await window_stats(db, monitor, "24h", NOW)
        assert s.up_checks == 360 and s.down_checks == 40 and s.unknown_checks == 20
        # 360 / (360 + 40) = 90% — 공백 6시간과 측정 불가 20회는 '정상'으로 세지 않음
        assert s.uptime_pct == 90.0
        # 관측 400회 / 기대 1440회
        assert s.coverage_pct == pytest.approx(27.8, abs=0.1)
        # 응답 시간은 HTTP 응답이 있는 검사만 (타임아웃 10,000ms 제외)
        assert s.max_response_ms == 109
        assert s.min_response_ms == 100
        assert 100 <= s.avg_response_ms <= 109


async def test_window_stats_no_data(sessionmaker) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user)
        await db.commit()
        s = await window_stats(db, monitor, "7d", NOW)
        assert s.uptime_pct is None
        assert s.coverage_pct == 0.0
        assert s.avg_response_ms is None


async def test_window_boundaries_and_downtime(sessionmaker) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user)
        # 8일 전 장애(7일 창 밖)와 2일 전 30분 장애, 진행 중 장애(10분 전 시작)
        db.add_all(
            [
                Incident(monitor_id=monitor.id, started_at=NOW - timedelta(days=8), detected_at=NOW - timedelta(days=8),
                         resolved_at=NOW - timedelta(days=8) + timedelta(hours=1), failed_checks=3),
                Incident(monitor_id=monitor.id, started_at=NOW - timedelta(days=2), detected_at=NOW - timedelta(days=2),
                         resolved_at=NOW - timedelta(days=2) + timedelta(minutes=30), failed_checks=3),
                Incident(monitor_id=monitor.id, started_at=NOW - timedelta(minutes=10),
                         detected_at=NOW - timedelta(minutes=8), failed_checks=3),
            ]
        )
        db.add(_check(monitor.id, NOW - timedelta(days=8), "up"))  # 7일 창 밖
        db.add(_check(monitor.id, NOW - timedelta(days=3), "up"))
        db.add(_check(monitor.id, NOW - timedelta(minutes=5), "down", status=503))
        await db.commit()

        d7 = await window_stats(db, monitor, "7d", NOW)
        assert (d7.up_checks, d7.down_checks) == (1, 1)
        assert d7.uptime_pct == 50.0
        assert d7.incidents == 2
        assert d7.downtime_seconds == 30 * 60 + 10 * 60

        d30 = await window_stats(db, monitor, "30d", NOW)
        assert d30.incidents == 3
        assert d30.downtime_seconds == 60 * 60 + 30 * 60 + 10 * 60

        h24 = await window_stats(db, monitor, "24h", NOW)
        assert h24.incidents == 1 and h24.downtime_seconds == 600


async def test_response_series_leaves_gaps_as_null(sessionmaker) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user)
        db.add(_check(monitor.id, NOW - timedelta(hours=2), "up", ms=200))
        db.add(_check(monitor.id, NOW - timedelta(hours=2) + M, "up", ms=400))
        await db.commit()
        points = await response_time_series(db, monitor.id, "24h", "Asia/Seoul", NOW)
        assert 95 <= len(points) <= 97
        filled = [p for p in points if p["avg_ms"] is not None]
        assert len(filled) == 1
        assert filled[0]["avg_ms"] == 300.0 and filled[0]["max_ms"] == 400
        assert filled[0]["uptime_pct"] == 100.0
        empty = [p for p in points if p["avg_ms"] is None]
        assert all(p["uptime_pct"] is None for p in empty)  # 공백 구간은 0% 도 100% 도 아닌 '데이터 없음'


async def test_daily_uptime_uses_local_days(sessionmaker) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user)
        # NOW = 2026-10-02 00:00 UTC = 2026-10-02 09:00 KST
        db.add(_check(monitor.id, NOW - timedelta(hours=10), "up"))  # 10/01 23:00 KST
        db.add(_check(monitor.id, NOW - timedelta(hours=8), "down"))  # 10/02 01:00 KST
        db.add(_check(monitor.id, NOW - timedelta(hours=7), "up"))  # 10/02 02:00 KST
        await db.commit()
        days = await daily_uptime(db, monitor.id, 3, "Asia/Seoul", NOW)
        assert [d["date"] for d in days] == ["2026-09-30", "2026-10-01", "2026-10-02"]
        assert days[0]["uptime_pct"] is None
        assert days[1]["uptime_pct"] == 100.0
        assert days[2]["uptime_pct"] == 50.0
