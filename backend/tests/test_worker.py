"""작업자 통합 테스트: 실제 DB + 모의 HTTP 서버로 정기 검사·장애·복구·재시작 재개를 검증."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.models import CheckResult, Incident, Monitor, Notification, WorkerHeartbeat
from app.services.checker import HttpChecker
from app.worker.runner import HostRateLimiter, Worker
from tests.helpers import count, make_monitor, make_user


def make_worker(settings, sessionmaker, resolver, worker_id="w-test") -> Worker:
    checker = HttpChecker(settings, resolver=resolver)
    return Worker(settings, checker=checker, sessionmaker=sessionmaker, worker_id=worker_id)


async def run_tick(worker: Worker, sessionmaker, monitor_id: int | None = None) -> None:
    """대상 모니터를 '지금 검사할 시각'으로 당긴 뒤 디스패치하고 완료까지 기다립니다."""
    async with sessionmaker() as db, db.begin():
        stmt = update(Monitor).values(next_check_at=datetime.now(UTC) - timedelta(seconds=1))
        if monitor_id is not None:
            stmt = stmt.where(Monitor.id == monitor_id)
        await db.execute(stmt)
    tasks = await worker.dispatch_due()
    if tasks:
        await asyncio.gather(*tasks)


async def setup_monitor(sessionmaker, url: str, **kw) -> int:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user, url=url, next_check_at=datetime.now(UTC), **kw)
        await db.commit()
        return monitor.id


async def test_failure_incident_and_recovery_end_to_end(sessionmaker, test_settings, fake_resolver, mock_server) -> None:
    mid = await setup_monitor(sessionmaker, mock_server.url("/flaky"), failure_threshold=3, timeout_seconds=2)
    worker = make_worker(test_settings, sessionmaker, fake_resolver)

    # 1) 정상
    await run_tick(worker, sessionmaker, mid)
    # 2) 일시적 장애 1회 → 장애 아님
    mock_server.state.mode = "fail"
    await run_tick(worker, sessionmaker, mid)
    mock_server.state.mode = "ok"
    await run_tick(worker, sessionmaker, mid)
    async with sessionmaker() as db:
        assert (await db.get(Monitor, mid)).status == "up"
        assert await count(db, Incident) == 0

    # 3) 연속 장애 3회(500) → 장애 판정
    mock_server.state.mode = "fail"
    mock_server.state.fail_status = 500
    for _ in range(3):
        await run_tick(worker, sessionmaker, mid)
    # 4) 장애 지속(타임아웃) → 추가 알림 없음
    mock_server.state.mode = "slow"
    mock_server.state.slow_seconds = 3
    await run_tick(worker, sessionmaker, mid)
    async with sessionmaker() as db:
        monitor = await db.get(Monitor, mid)
        assert monitor.status == "down"
        assert monitor.consecutive_failures == 4
        assert monitor.last_error_type == "timeout"
        incident = await db.scalar(select(Incident))
        assert incident.resolved_at is None and incident.cause_type == "status"
        assert await count(db, Notification, Notification.kind == "down") == 1

    # 5) 복구
    mock_server.state.mode = "ok"
    await run_tick(worker, sessionmaker, mid)
    async with sessionmaker() as db:
        monitor = await db.get(Monitor, mid)
        incident = await db.scalar(select(Incident))
        assert monitor.status == "up"
        assert incident.resolved_at is not None and incident.duration_seconds >= 0
        kinds = (await db.scalars(select(Notification.kind).order_by(Notification.id))).all()
        assert kinds == ["down", "up"]
        outcomes = (await db.scalars(select(CheckResult.outcome).order_by(CheckResult.id))).all()
        assert outcomes == ["up", "down", "up", "down", "down", "down", "down", "up"]
        assert worker.checks_performed == 8


async def test_next_check_is_scheduled_by_interval(sessionmaker, test_settings, fake_resolver, mock_server) -> None:
    mid = await setup_monitor(sessionmaker, mock_server.url("/ok"), interval_seconds=120)
    worker = make_worker(test_settings, sessionmaker, fake_resolver)
    before = datetime.now(UTC)
    await run_tick(worker, sessionmaker, mid)
    async with sessionmaker() as db:
        monitor = await db.get(Monitor, mid)
        assert monitor.next_check_at >= before + timedelta(seconds=119)
    # 아직 예정 시각 전이면 다시 검사하지 않음
    assert await worker.dispatch_due() == []


async def test_resume_after_restart(sessionmaker, test_settings, fake_resolver, mock_server) -> None:
    """작업자가 오래 중단되어 밀린 검사는 재시작 시 짧은 구간에 분산 예약된 뒤 정상 재개된다."""
    mid = await setup_monitor(sessionmaker, mock_server.url("/ok"))
    first = make_worker(test_settings, sessionmaker, fake_resolver, "w-1")
    await run_tick(first, sessionmaker, mid)
    await first.heartbeat()

    # 작업자 중단: 2시간 동안 검사 없음
    async with sessionmaker() as db, db.begin():
        await db.execute(update(Monitor).values(next_check_at=datetime.now(UTC) - timedelta(hours=2)))

    second = make_worker(test_settings, sessionmaker, fake_resolver, "w-2")  # 재시작된 프로세스
    assert await second.resume_after_restart() == 1
    async with sessionmaker() as db:
        monitor = await db.get(Monitor, mid)
        assert datetime.now(UTC) - timedelta(seconds=1) <= monitor.next_check_at <= datetime.now(UTC) + timedelta(seconds=31)
    await run_tick(second, sessionmaker, mid)
    await second.heartbeat()
    async with sessionmaker() as db:
        assert await count(db, CheckResult) == 2
        assert {w.worker_id for w in (await db.scalars(select(WorkerHeartbeat))).all()} == {"w-1", "w-2"}


async def test_two_workers_do_not_double_check(sessionmaker, test_settings, fake_resolver, mock_server) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        for i in range(6):
            await make_monitor(db, user, name=f"m{i}", url=mock_server.url(f"/ok?{i}"), next_check_at=datetime.now(UTC))
        await db.commit()
    w1 = make_worker(test_settings, sessionmaker, fake_resolver, "w-1")
    w2 = make_worker(test_settings, sessionmaker, fake_resolver, "w-2")
    t1, t2 = await asyncio.gather(w1.dispatch_due(), w2.dispatch_due())
    await asyncio.gather(*t1, *t2)
    async with sessionmaker() as db:
        assert await count(db, CheckResult) == 6  # 각 모니터 정확히 1회


async def test_paused_or_deleted_during_check_result_discarded(sessionmaker, test_settings, fake_resolver, mock_server) -> None:
    mid = await setup_monitor(sessionmaker, mock_server.url("/delay/1"), timeout_seconds=3)
    worker = make_worker(test_settings, sessionmaker, fake_resolver)
    async with sessionmaker() as db, db.begin():
        await db.execute(update(Monitor).values(next_check_at=datetime.now(UTC) - timedelta(seconds=1)))
    tasks = await worker.dispatch_due()
    async with sessionmaker() as db, db.begin():  # 검사 도중 일시 정지
        await db.execute(update(Monitor).where(Monitor.id == mid).values(is_active=False, status="paused"))
    await asyncio.gather(*tasks)
    async with sessionmaker() as db:
        assert await count(db, CheckResult) == 0


async def test_manual_check_is_flagged(sessionmaker, test_settings, fake_resolver, mock_server) -> None:
    mid = await setup_monitor(sessionmaker, mock_server.url("/ok"))
    async with sessionmaker() as db, db.begin():
        await db.execute(update(Monitor).values(manual_check_requested_at=datetime.now(UTC)))
    worker = make_worker(test_settings, sessionmaker, fake_resolver)
    await asyncio.gather(*(await worker.dispatch_due()))
    async with sessionmaker() as db:
        check = await db.scalar(select(CheckResult))
        assert check.is_manual is True
        assert (await db.get(Monitor, mid)).manual_check_requested_at is None


def test_host_rate_limiter() -> None:
    limiter = HostRateLimiter(per_minute=3)
    assert [limiter.allow("a.example", now=0) for _ in range(4)] == [True, True, True, False]
    assert limiter.allow("b.example", now=0) is True  # 호스트별 독립
    assert limiter.allow("a.example", now=20) is True  # 20초 후 토큰 1개 회복


async def test_host_rate_limit_defers_instead_of_skipping(sessionmaker, test_settings, fake_resolver, mock_server) -> None:
    settings = test_settings.model_copy(update={"check_per_host_per_minute": 2})
    async with sessionmaker() as db:
        user = await make_user(db)
        for i in range(4):
            await make_monitor(db, user, name=f"m{i}", url=mock_server.url(f"/ok?{i}"), next_check_at=datetime.now(UTC))
        await db.commit()
    worker = make_worker(settings, sessionmaker, fake_resolver)
    await asyncio.gather(*(await worker.dispatch_due()))
    async with sessionmaker() as db:
        assert await count(db, CheckResult) == 2
        deferred = (await db.scalars(select(Monitor).where(Monitor.last_checked_at.is_(None)))).all()
        assert len(deferred) == 2
        assert all(m.next_check_at > datetime.now(UTC) for m in deferred)  # 건너뛰지 않고 뒤로 미룸


async def test_cleanup_respects_retention(sessionmaker, test_settings, fake_resolver) -> None:
    async with sessionmaker() as db:
        user = await make_user(db)
        monitor = await make_monitor(db, user)
        now = datetime.now(UTC)
        for days in (1, 89, 91, 200):
            db.add(CheckResult(monitor_id=monitor.id, checked_at=now - timedelta(days=days), outcome="up",
                               status_code=200, response_time_ms=10, redirect_count=0, is_manual=False))
        await db.commit()
    await make_worker(test_settings, sessionmaker, fake_resolver).cleanup()
    async with sessionmaker() as db:
        assert await count(db, CheckResult) == 2
