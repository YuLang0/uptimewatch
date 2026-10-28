"""E2E 테스트 DB 초기화 후 마이그레이션 (python -m scripts.reset_e2e_db)."""

import asyncio
import os
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

URL = os.environ["DATABASE_URL"]
if "e2e" not in URL:
    sys.exit("안전장치: DATABASE_URL 에 'e2e' 가 포함된 DB 만 초기화합니다.")


async def main() -> None:
    engine = create_async_engine(URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


asyncio.run(main())
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
