"""HTTP 검사기: 모의 서버로 정상·오류·타임아웃·DNS·TLS 상황을 재현합니다(외부 사이트 미사용)."""

from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime, timedelta

import pytest
import trustme

from app.services.checker import CheckTarget, HttpChecker
from tests.mock_server import MockServer


def target(url: str, **kw) -> CheckTarget:
    kw.setdefault("timeout_seconds", 3)
    return CheckTarget(monitor_id=1, url=url, **kw)


@pytest.fixture
def checker(test_settings, fake_resolver) -> HttpChecker:
    return HttpChecker(test_settings, resolver=fake_resolver)


async def test_http_200_is_up(checker, mock_server) -> None:
    result = await checker.check(target(mock_server.url("/ok")))
    assert result.outcome == "up"
    assert result.status_code == 200
    assert result.response_time_ms is not None and result.response_time_ms >= 0
    assert result.error_type is None


async def test_http_500_is_down(checker, mock_server) -> None:
    result = await checker.check(target(mock_server.url("/status/500")))
    assert result.outcome == "down"
    assert result.status_code == 500
    assert result.error_type == "status"
    assert "500" in result.error_message


async def test_custom_expected_status(checker, mock_server) -> None:
    result = await checker.check(target(mock_server.url("/status/404"), expected_status="404"))
    assert result.outcome == "up"
    result = await checker.check(target(mock_server.url("/status/204"), expected_status="200-299,404"))
    assert result.outcome == "up"


async def test_timeout(checker, mock_server) -> None:
    result = await checker.check(target(mock_server.url("/delay/3"), timeout_seconds=1))
    assert result.outcome == "down"
    assert result.error_type == "timeout"
    assert result.status_code is None
    assert 900 <= result.response_time_ms < 2500


async def test_dns_error(checker, mock_server) -> None:
    result = await checker.check(target(f"http://does-not-exist.example:{mock_server.port}/"))
    assert result.outcome == "down"
    assert result.error_type == "dns"


async def test_connection_refused(checker) -> None:
    with socket.socket() as s:  # 사용하지 않는 포트 확보
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    result = await checker.check(target(f"http://127.0.0.1:{free_port}/"))
    assert result.outcome == "down"
    assert result.error_type == "connection"


async def test_head_method(checker, mock_server) -> None:
    result = await checker.check(target(mock_server.url("/ok"), method="HEAD"))
    assert result.outcome == "up"


async def test_redirect_followed(checker, mock_server) -> None:
    result = await checker.check(target(mock_server.url("/redirect?to=/ok")))
    assert result.outcome == "up"
    assert result.redirect_count == 1


async def test_redirect_not_followed_when_disabled(checker, mock_server) -> None:
    result = await checker.check(target(mock_server.url("/redirect?to=/ok"), follow_redirects=False))
    assert result.outcome == "down" and result.status_code == 302
    result = await checker.check(
        target(mock_server.url("/redirect?to=/ok"), follow_redirects=False, expected_status="302")
    )
    assert result.outcome == "up"


async def test_redirect_loop_is_limited(checker, mock_server, test_settings) -> None:
    result = await checker.check(target(mock_server.url("/redirect-loop")))
    assert result.outcome == "down"
    assert result.error_type == "redirect"
    assert result.redirect_count == test_settings.check_max_redirects


async def test_large_body_is_capped(checker, mock_server) -> None:
    # 5MB 본문 중 설정값(64KB)까지만 읽고 연결을 닫는다 — 결과는 정상.
    result = await checker.check(target(mock_server.url("/big")))
    assert result.outcome == "up"
    assert result.status_code == 200


# ---------- TLS ----------
@pytest.fixture(scope="module")
def ca() -> trustme.CA:
    return trustme.CA()


def _https_server(ca: trustme.CA, hostname: str, not_after: datetime | None = None) -> MockServer:
    cert = ca.issue_cert(hostname, not_after=not_after)
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    cert.configure_cert(ctx)
    return MockServer(ssl_context=ctx).start()


def _client_ctx(ca: trustme.CA) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ca.configure_trust(ctx)
    return ctx


async def test_tls_certificate_expiry_is_recorded(ca, test_settings, fake_resolver) -> None:
    expires = (datetime.now(UTC) + timedelta(days=40)).replace(microsecond=0)
    server = _https_server(ca, "secure.example", not_after=expires)
    try:
        checker = HttpChecker(test_settings, resolver=fake_resolver, ssl_context=_client_ctx(ca))
        # secure.example → 127.0.0.1 로 고정 연결하면서 SNI/인증서 검증은 secure.example 로 수행
        result = await checker.check(target(server.url("/ok", host="secure.example")))
        assert result.outcome == "up", result.error_message
        assert result.tls_expires_at is not None
        assert abs((result.tls_expires_at - expires).total_seconds()) < 2
    finally:
        server.stop()


async def test_expired_certificate_is_down(ca, test_settings, fake_resolver) -> None:
    server = _https_server(ca, "secure.example", not_after=datetime.now(UTC) - timedelta(days=1))
    try:
        checker = HttpChecker(test_settings, resolver=fake_resolver, ssl_context=_client_ctx(ca))
        result = await checker.check(target(server.url("/ok", host="secure.example")))
        assert result.outcome == "down"
        assert result.error_type == "tls"
        assert "만료" in result.error_message
    finally:
        server.stop()


async def test_hostname_mismatch_is_down(ca, test_settings, fake_resolver) -> None:
    server = _https_server(ca, "other.example")
    try:
        checker = HttpChecker(test_settings, resolver=fake_resolver, ssl_context=_client_ctx(ca))
        result = await checker.check(target(server.url("/ok", host="secure.example")))
        assert result.outcome == "down"
        assert result.error_type == "tls"
    finally:
        server.stop()


async def test_untrusted_certificate_is_down(ca, test_settings, fake_resolver) -> None:
    server = _https_server(ca, "secure.example")
    try:
        checker = HttpChecker(test_settings, resolver=fake_resolver)  # 시스템 CA 만 신뢰
        result = await checker.check(target(server.url("/ok", host="secure.example")))
        assert result.outcome == "down"
        assert result.error_type == "tls"
    finally:
        server.stop()
