"""SSRF 방어: URL 정책, 주소 정책, DNS 재바인딩, 리다이렉트 목적지 검증."""

from __future__ import annotations

import ipaddress

import pytest

from app.security.ssrf import (
    AddressPolicy,
    InvalidURLError,
    SSRFError,
    resolve_and_validate,
    validate_url,
)
from app.services.checker import CheckTarget, HttpChecker, SafeNetworkBackend
from tests.conftest import FakeResolver

DEFAULT = AddressPolicy()  # 운영 기본 정책: 80/443/8080/8443, 예외 없음
ANY_PORT = AddressPolicy(allowed_ports=None)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.1/",
        "http://2130706433/",  # 10진 정수 표기 127.0.0.1
        "http://0x7f000001/",  # 16진 표기
        "http://0x7f.0x0.0x0.0x1/",
        "http://0177.0.0.1/",  # 8진 표기
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",  # IPv4 매핑 IPv6
        "http://[::ffff:7f00:1]/",
        "http://[64:ff9b::7f00:1]/",  # NAT64 내장
        "http://[2002:7f00:1::]/",  # 6to4 내장
        "http://0.0.0.0/",
        "http://10.1.2.3/",
        "http://172.16.0.1/",
        "http://192.168.0.1/",
        "http://100.64.0.1/",  # CGNAT
        "http://169.254.169.254/latest/meta-data/",  # AWS/GCP/Azure 메타데이터
        "http://[fd00:ec2::254]/",  # AWS IPv6 메타데이터
        "http://[fe80::1]/",
        "http://224.0.0.1/",
        "http://localhost/",
        "http://LOCALHOST./",
        "http://foo.localhost/",
        "http://metadata.google.internal/",
        "http://printer.local/",
        "http://db.svc.cluster.local/",
        "http://host.docker.internal/",
        "http://intranet/",  # 단일 라벨
        "http://example.com:22/",  # 허용되지 않은 포트
        "http://example.com:6379/",
    ],
)
def test_blocked_targets(url: str) -> None:
    with pytest.raises(SSRFError):
        validate_url(url, DEFAULT)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "javascript:alert(1)",
        "http://user:pass@example.com/",  # 인증정보 저장 금지
        "http://user@example.com/",
        "http:///nohost",
        "http://exa mple.com/",
        "http://example.com\\@evil.com/",
        "",
        "http://" + "a" * 2050 + ".com/",
    ],
)
def test_invalid_urls(url: str) -> None:
    with pytest.raises((InvalidURLError, SSRFError)):
        validate_url(url, DEFAULT)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://Example.COM", "https://example.com/"),
        ("https://example.com:443/path?q=1#frag", "https://example.com/path?q=1"),
        ("http://example.com:8080/health", "http://example.com:8080/health"),
        ("https://한국.kr/", "https://xn--3e0b707e.kr/"),
        ("https://93.184.215.14/", "https://93.184.215.14/"),
        ("https://[2606:2800:220:1:248:1893:25c8:1946]/", "https://[2606:2800:220:1:248:1893:25c8:1946]/"),
    ],
)
def test_public_urls_are_normalized(url: str, expected: str) -> None:
    assert validate_url(url, DEFAULT).url == expected


@pytest.mark.parametrize(
    "ip",
    ["8.8.8.8", "1.1.1.1", "93.184.215.14", "2606:4700:4700::1111"],
)
def test_public_ips_allowed(ip: str) -> None:
    assert DEFAULT.is_ip_allowed(ipaddress.ip_address(ip))


def test_explicit_exception_only_allows_listed_network() -> None:
    policy = AddressPolicy(allowed_ports=None, allowed_networks=(ipaddress.ip_network("127.0.0.1/32"),))
    assert policy.is_ip_allowed(ipaddress.ip_address("127.0.0.1"))
    assert not policy.is_ip_allowed(ipaddress.ip_address("127.0.0.2"))
    assert not policy.is_ip_allowed(ipaddress.ip_address("10.0.0.1"))


@pytest.mark.parametrize(
    "host",
    ["evil.example", "metadata.example", "mixed.example", "v6private.example", "mapped.example"],
)
async def test_dns_answers_with_internal_addresses_are_blocked(host: str, fake_resolver: FakeResolver) -> None:
    with pytest.raises(SSRFError):
        await resolve_and_validate(host, 80, DEFAULT, fake_resolver)


async def test_dns_public_answer_passes(fake_resolver: FakeResolver) -> None:
    assert await resolve_and_validate("public.example", 443, DEFAULT, fake_resolver) == ["93.184.215.14"]


async def test_dns_rebinding_is_blocked_at_connect_time(mock_server, strict_settings) -> None:
    """등록 시점엔 공인 IP, 검사 시점엔 루프백으로 바뀌는 DNS 재바인딩 공격."""
    answers = iter([["93.184.215.14"], ["127.0.0.1"], ["127.0.0.1"]])
    resolver = FakeResolver({"rebind.example": lambda: next(answers)})

    # 1) 등록 시점 검증 통과 (공인 IP)
    await resolve_and_validate("rebind.example", mock_server.port, ANY_PORT, resolver)

    # 2) 검사 시점: 루프백으로 해석 → 연결 전에 차단, 모의 서버에 요청이 도달하지 않음
    checker = HttpChecker(strict_settings, policy=ANY_PORT, resolver=resolver)
    result = await checker.check(
        CheckTarget(monitor_id=1, url=f"http://rebind.example:{mock_server.port}/flaky", timeout_seconds=3)
    )
    assert result.outcome == "down"
    assert result.error_type == "blocked"
    assert mock_server.state.hits == 0


async def test_connection_is_pinned_to_validated_ip(mock_server, test_settings) -> None:
    """한 번 해석·검증한 IP 로 직접 연결하므로 두 번째 DNS 조회(재바인딩 기회)가 없다."""
    calls = {"n": 0}

    def answer() -> list[str]:
        calls["n"] += 1
        return ["127.0.0.1"] if calls["n"] == 1 else ["10.9.9.9"]

    resolver = FakeResolver({"pinned.example": answer})
    policy = AddressPolicy(allowed_ports=None, allowed_networks=(ipaddress.ip_network("127.0.0.1/32"),))
    checker = HttpChecker(test_settings, policy=policy, resolver=resolver)
    result = await checker.check(CheckTarget(monitor_id=1, url=f"http://pinned.example:{mock_server.port}/ok"))
    assert result.outcome == "up", result.error_message
    assert calls["n"] == 1
    assert result.connected_ip == "127.0.0.1"


async def test_safe_backend_refuses_internal_ip_even_if_url_check_skipped() -> None:
    backend = SafeNetworkBackend(DEFAULT, FakeResolver({"x.example": ["10.0.0.1"]}))
    with pytest.raises(SSRFError):
        await backend.connect_tcp("x.example", 443)
    with pytest.raises(SSRFError):
        await backend.connect_tcp("169.254.169.254", 80)


@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://[::1]/",
        "http://localhost/",
        "http://evil.example/",  # 가짜 DNS: 10.0.0.5
        "http://user:pass@public.example/",
        "http://2130706433/",
    ],
)
async def test_redirect_to_internal_destination_is_blocked(location: str, mock_server, test_settings, fake_resolver) -> None:
    checker = HttpChecker(test_settings, resolver=fake_resolver)
    url = mock_server.url(f"/redirect?to={location}")
    result = await checker.check(CheckTarget(monitor_id=1, url=url, timeout_seconds=3))
    assert result.outcome == "down"
    assert result.error_type in ("blocked", "redirect"), result
    assert result.redirect_count == 1


async def test_redirect_to_non_http_scheme_is_not_followed(mock_server, test_settings, fake_resolver) -> None:
    checker = HttpChecker(test_settings, resolver=fake_resolver)
    result = await checker.check(
        CheckTarget(monitor_id=1, url=mock_server.url("/redirect?to=file:///etc/passwd"), timeout_seconds=3)
    )
    assert result.outcome == "down"
    assert result.error_type == "redirect"
