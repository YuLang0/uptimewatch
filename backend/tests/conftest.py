from __future__ import annotations

import asyncio
import os

# 앱 모듈을 import 하기 전에 테스트 환경변수를 설정합니다.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://uptimewatch:uptimewatch@localhost:5432/uptimewatch_test"
)
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"
for _var in ("SMTP_HOST", "SMTP_FROM", "SMTP_USERNAME", "SMTP_PASSWORD", "CHECK_EGRESS_PROXY", "CHECK_ALLOWED_CIDRS"):
    os.environ.pop(_var, None)

from collections.abc import AsyncIterator, Callable  # noqa: E402
from dataclasses import dataclass  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app import db as app_db  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.security.ssrf import DNSResolutionError  # noqa: E402
from tests.mock_server import MockServer  # noqa: E402

TEST_DB_URL = os.environ["DATABASE_URL"]
TABLES = (
    "notification_deliveries, notifications, status_page_monitors, status_pages, check_results, "
    "incidents, monitors, notification_settings, user_sessions, users, worker_heartbeats"
)


async def _reset_schema() -> None:
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """테스트 DB 를 비우고 Alembic 마이그레이션으로 스키마를 생성합니다(마이그레이션 검증 겸용)."""
    asyncio.run(_reset_schema())
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.attributes["database_url"] = TEST_DB_URL
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest.fixture
async def db_engine() -> AsyncIterator[None]:
    engine = app_db.init_engine(TEST_DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield
    await app_db.dispose_engine()


@pytest.fixture
def sessionmaker(db_engine):
    return app_db.get_sessionmaker()


class FakeResolver:
    """가짜 DNS. 값이 callable 이면 호출할 때마다 결과가 달라질 수 있습니다(DNS 재바인딩 재현)."""

    def __init__(self, mapping: dict[str, list[str] | Callable[[], list[str]]] | None = None) -> None:
        self.mapping = dict(mapping or {})
        self.calls: list[str] = []

    async def __call__(self, host: str, port: int) -> list[str]:
        self.calls.append(host)
        value = self.mapping.get(host)
        if value is None:
            raise DNSResolutionError(f"NXDOMAIN {host}")
        return list(value() if callable(value) else value)


@pytest.fixture
def fake_resolver() -> FakeResolver:
    return FakeResolver(
        {
            "public.example": ["93.184.215.14"],
            "mock.example": ["127.0.0.1"],
            "secure.example": ["127.0.0.1"],
            "evil.example": ["10.0.0.5"],
            "metadata.example": ["169.254.169.254"],
            "mixed.example": ["93.184.215.14", "192.168.1.10"],
            "v6private.example": ["fd00::1"],
            "mapped.example": ["::ffff:127.0.0.1"],
        }
    )


@pytest.fixture
def test_settings() -> Settings:
    """모의 서버(127.0.0.1)를 검사할 수 있도록 루프백만 명시적으로 허용한 설정."""
    return Settings(
        database_url=TEST_DB_URL,
        environment="test",
        check_allowed_cidrs="127.0.0.1/32",
        check_allowed_ports="",
        check_max_response_bytes=64 * 1024,
        worker_tick_seconds=0.2,
    )


@pytest.fixture
def strict_settings() -> Settings:
    """운영과 동일한 기본 SSRF 정책(예외 없음)."""
    return Settings(database_url=TEST_DB_URL, environment="test", check_allowed_ports="")


@pytest.fixture(scope="session")
def mock_server() -> MockServer:
    server = MockServer().start()
    yield server
    server.stop()


@pytest.fixture(autouse=True)
def _reset_mock_state(request) -> None:
    if "mock_server" in request.fixturenames:
        server = request.getfixturevalue("mock_server")
        server.state.mode = "ok"
        server.state.fail_status = 503
        server.state.slow_seconds = 5.0
        server.state.hits = 0


@dataclass
class ApiUser:
    client: httpx.AsyncClient
    email: str
    csrf: str
    user_id: int

    async def get(self, url: str, **kw) -> httpx.Response:
        return await self.client.get(url, **kw)

    async def post(self, url: str, **kw) -> httpx.Response:
        return await self.client.post(url, headers={"X-CSRF-Token": self.csrf}, **kw)

    async def patch(self, url: str, **kw) -> httpx.Response:
        return await self.client.patch(url, headers={"X-CSRF-Token": self.csrf}, **kw)

    async def put(self, url: str, **kw) -> httpx.Response:
        return await self.client.put(url, headers={"X-CSRF-Token": self.csrf}, **kw)

    async def delete(self, url: str, **kw) -> httpx.Response:
        return await self.client.delete(url, headers={"X-CSRF-Token": self.csrf}, **kw)


@pytest.fixture
async def app(db_engine, fake_resolver):
    from app.api.deps import get_resolver, reset_limiters
    from app.main import app as fastapi_app

    get_settings.cache_clear()
    fastapi_app.dependency_overrides[get_resolver] = lambda: fake_resolver
    reset_limiters()
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
async def make_client(app):
    clients: list[httpx.AsyncClient] = []

    def _make() -> httpx.AsyncClient:
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
        clients.append(c)
        return c

    yield _make
    for c in clients:
        await c.aclose()


@pytest.fixture
def register(make_client):
    async def _register(email: str = "alice@example.com", password: str = "correct-horse-1") -> ApiUser:
        client = make_client()
        r = await client.post("/api/auth/register", json={"email": email, "password": password, "display_name": "테스터"})
        assert r.status_code == 201, r.text
        body = r.json()
        return ApiUser(client=client, email=email, csrf=body["csrf_token"], user_id=body["user"]["id"])

    return _register
