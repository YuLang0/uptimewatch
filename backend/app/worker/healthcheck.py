"""컨테이너 헬스체크: 이 호스트의 작업자가 최근 하트비트를 남겼는지 확인 (python -m app.worker.healthcheck)."""

from __future__ import annotations

import asyncio
import socket
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker
from app.models import WorkerHeartbeat


async def main() -> int:
    settings = get_settings()
    prefix = socket.gethostname()[:30] + "-"
    async with get_sessionmaker()() as db:
        last = await db.scalar(
            select(func.max(WorkerHeartbeat.last_seen_at)).where(WorkerHeartbeat.worker_id.startswith(prefix))
        )
    await dispose_engine()
    if last is None or datetime.now(UTC) - last > timedelta(seconds=settings.worker_stale_after_seconds):
        print("worker heartbeat stale", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
