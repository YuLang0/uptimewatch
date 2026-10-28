"""작업자 실행: python -m app.worker"""

from __future__ import annotations

import asyncio
import logging

from app.db import dispose_engine
from app.worker.runner import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def main() -> None:
    worker = Worker()
    try:
        await worker.run_forever()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
