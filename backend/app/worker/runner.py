"""백그라운드 검사 작업자.

스케줄링은 데이터베이스(monitors.next_check_at)에 저장되므로 프로세스·서버가 재시작되어도
그대로 이어서 검사합니다. APScheduler 는 주기 작업(디스패치·알림 발송·하트비트·정리)을 구동합니다.

동시성
- `SELECT ... FOR UPDATE SKIP LOCKED` 로 검사 대상을 선점하므로 작업자를 여러 개 실행해도 중복 검사하지 않습니다.
- 전역 동시 검사 수(semaphore)와 호스트별 분당 검사 수(token bucket)를 제한해 대상 사이트에 부하를 주지 않습니다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import signal
import socket
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.models import CheckResult, Monitor, Notification, UserSession, WorkerHeartbeat
from app.services.checker import CheckTarget, HttpChecker
from app.services.email import EmailSender
from app.services.monitoring import record_check
from app.services.notifications import process_pending_deliveries

logger = logging.getLogger("uptimewatch.worker")


class HostRateLimiter:
    """호스트별 토큰 버킷 (분당 N회)."""

    def __init__(self, per_minute: int) -> None:
        self.capacity = max(1, per_minute)
        self.rate = self.capacity / 60.0
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, host: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        tokens, last = self._buckets.get(host, (float(self.capacity), now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens < 1:
            self._buckets[host] = (tokens, now)
            return False
        self._buckets[host] = (tokens - 1, now)
        return True


class Worker:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        checker: HttpChecker | None = None,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        email_sender: EmailSender | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.checker = checker or HttpChecker(self.settings)
        self.sessionmaker = sessionmaker or get_sessionmaker()
        self.email_sender = email_sender or EmailSender(self.settings)
        self.worker_id = worker_id or f"{socket.gethostname()[:30]}-{os.getpid()}-{secrets.token_hex(3)}"
        self.started_at = datetime.now(UTC)
        self.semaphore = asyncio.Semaphore(self.settings.check_concurrency)
        self.host_limiter = HostRateLimiter(self.settings.check_per_host_per_minute)
        self.in_flight: dict[int, asyncio.Task] = {}
        self.checks_performed = 0
        self._stop = asyncio.Event()

    # ---------- 재시작 후 재개 ----------
    async def resume_after_restart(self) -> int:
        """중단 기간 동안 밀린 검사를 짧은 구간에 분산해 다시 예약합니다(한꺼번에 몰리지 않도록)."""
        async with self.sessionmaker() as db, db.begin():
            result = await db.execute(
                text(
                    """
                    UPDATE monitors
                    SET next_check_at = now() + (random() * least(interval_seconds, 30)) * interval '1 second'
                    WHERE is_active AND (next_check_at IS NULL OR next_check_at < now())
                    """
                )
            )
        count = result.rowcount or 0
        if count:
            logger.info("재시작 후 밀린 검사 %d건을 다시 예약했습니다.", count)
        return count

    # ---------- 디스패치 ----------
    async def dispatch_due(self) -> list[asyncio.Task]:
        now = datetime.now(UTC)
        targets: list[CheckTarget] = []
        async with self.sessionmaker() as db, db.begin():
            monitors = (
                await db.scalars(
                    select(Monitor)
                    .where(Monitor.is_active.is_(True), Monitor.next_check_at <= now)
                    .order_by(Monitor.next_check_at)
                    .limit(self.settings.worker_batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for m in monitors:
                if m.id in self.in_flight:
                    m.next_check_at = now + timedelta(seconds=5)
                    continue
                host = urlsplit(m.url).hostname or ""
                if not self.host_limiter.allow(host):
                    # 같은 호스트에 대한 검사가 너무 많음 → 잠시 뒤로 미룸(건너뛰지 않음)
                    m.next_check_at = now + timedelta(seconds=5 + secrets.randbelow(10))
                    continue
                targets.append(
                    CheckTarget(
                        monitor_id=m.id,
                        url=m.url,
                        method=m.method,
                        timeout_seconds=m.timeout_seconds,
                        expected_status=m.expected_status,
                        follow_redirects=m.follow_redirects,
                        is_manual=m.manual_check_requested_at is not None,
                    )
                )
                m.next_check_at = now + timedelta(seconds=m.interval_seconds)
                m.manual_check_requested_at = None
        tasks = []
        for target in targets:
            task = asyncio.create_task(self.run_check(target), name=f"check-{target.monitor_id}")
            self.in_flight[target.monitor_id] = task
            task.add_done_callback(lambda _t, mid=target.monitor_id: self.in_flight.pop(mid, None))
            tasks.append(task)
        return tasks

    async def run_check(self, target: CheckTarget) -> None:
        try:
            async with self.semaphore:
                outcome = await self.checker.check(target)
            async with self.sessionmaker() as db, db.begin():
                monitor = await db.get(Monitor, target.monitor_id, with_for_update=True)
                if monitor is None or not monitor.is_active or monitor.url != target.url:
                    # 검사 도중 삭제·일시 정지·대상 변경 → 결과 폐기
                    return
                await record_check(db, monitor, outcome, self.settings, is_manual=target.is_manual)
            self.checks_performed += 1
        except Exception:
            logger.exception("monitor %s 검사 결과 처리 실패", target.monitor_id)

    # ---------- 주기 작업 ----------
    async def deliver_notifications(self) -> int:
        try:
            return await process_pending_deliveries(self.sessionmaker, self.email_sender, self.settings)
        except Exception:
            logger.exception("알림 발송 처리 실패")
            return 0

    async def heartbeat(self) -> None:
        now = datetime.now(UTC)
        async with self.sessionmaker() as db, db.begin():
            stmt = pg_insert(WorkerHeartbeat).values(
                worker_id=self.worker_id,
                started_at=self.started_at,
                last_seen_at=now,
                checks_performed=self.checks_performed,
            )
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=[WorkerHeartbeat.worker_id],
                    set_={"last_seen_at": now, "checks_performed": self.checks_performed},
                )
            )

    async def cleanup(self) -> None:
        now = datetime.now(UTC)
        async with self.sessionmaker() as db, db.begin():
            checks = await db.execute(
                delete(CheckResult).where(
                    CheckResult.checked_at < now - timedelta(days=self.settings.check_retention_days)
                )
            )
            notes = await db.execute(
                delete(Notification).where(
                    Notification.created_at < now - timedelta(days=self.settings.notification_retention_days)
                )
            )
            await db.execute(delete(UserSession).where(UserSession.expires_at < now))
            await db.execute(delete(WorkerHeartbeat).where(WorkerHeartbeat.last_seen_at < now - timedelta(days=1)))
        logger.info("정리 완료: 검사 결과 %s건, 알림 %s건 삭제", checks.rowcount, notes.rowcount)

    # ---------- 실행 ----------
    async def _safe(self, coro_fn) -> None:
        try:
            await coro_fn()
        except Exception:
            logger.exception("%s 실패", coro_fn.__name__)

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.stop)
            except NotImplementedError:  # pragma: no cover
                pass

        logger.info("작업자 시작: id=%s, 동시 검사=%d", self.worker_id, self.settings.check_concurrency)
        await self.heartbeat()
        await self.resume_after_restart()

        scheduler = AsyncIOScheduler(timezone="UTC")
        common = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 30}
        scheduler.add_job(
            self._safe, "interval", args=[self.dispatch_due], seconds=self.settings.worker_tick_seconds,
            next_run_time=datetime.now(UTC), id="dispatch", **common,
        )
        scheduler.add_job(
            self._safe, "interval", args=[self.deliver_notifications], seconds=10, id="deliver", **common
        )
        scheduler.add_job(
            self._safe, "interval", args=[self.heartbeat], seconds=self.settings.worker_heartbeat_seconds,
            id="heartbeat", **common,
        )
        scheduler.add_job(
            self._safe, "interval", args=[self.cleanup], hours=6,
            next_run_time=datetime.now(UTC) + timedelta(minutes=1), id="cleanup", **common,
        )
        scheduler.start()
        try:
            await self._stop.wait()
        finally:
            logger.info("작업자 종료 중: 진행 중인 검사 %d건 마무리 대기", len(self.in_flight))
            scheduler.shutdown(wait=False)
            if self.in_flight:
                await asyncio.wait(list(self.in_flight.values()), timeout=self.settings.check_max_timeout_seconds + 5)
            await self._safe(self.heartbeat)
            logger.info("작업자 종료")
