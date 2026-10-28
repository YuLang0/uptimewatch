"""실제 HTTP/HTTPS 검사기.

- 모든 연결은 SafeNetworkBackend 를 거치며, 연결 직전 DNS 해석 → 주소 정책 검증 → 검증된 IP 로 직접 연결합니다.
- 리다이렉트는 직접 추적하며 매 홉마다 URL 정책과 주소 정책을 다시 적용합니다.
- 응답 본문은 최대 N 바이트까지만 읽고 저장하지 않습니다. 응답 헤더도 저장하지 않습니다.
- 요청 헤더는 고정(User-Agent, Accept)이며 사용자 정의 헤더·인증정보를 보내지 않습니다.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpcore
import httpx
from httpcore._backends.anyio import AnyIOBackend
from httpcore._backends.base import SOCKET_OPTION, AsyncNetworkBackend, AsyncNetworkStream

from app.config import Settings
from app.security.ssrf import (
    AddressPolicy,
    DNSResolutionError,
    Resolver,
    SSRFError,
    resolve_and_validate,
    system_resolver,
    validate_url,
)
from app.services.status_codes import status_matches

logger = logging.getLogger(__name__)

REDIRECT_CODES = {301, 302, 303, 307, 308}


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CheckTarget:
    monitor_id: int
    url: str
    method: str = "GET"
    timeout_seconds: float = 10
    expected_status: str = "200-299"
    follow_redirects: bool = True
    is_manual: bool = False


@dataclass
class CheckOutcome:
    outcome: str  # up | down | error
    checked_at: datetime
    status_code: int | None = None
    response_time_ms: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    redirect_count: int = 0
    tls_expires_at: datetime | None = None
    connected_ip: str | None = None  # 진단용(저장·노출하지 않음)

    @property
    def is_success(self) -> bool:
        return self.outcome == "up"


class SafeNetworkBackend(AsyncNetworkBackend):
    """연결 시점에 해석·검증한 IP 로만 접속하는 네트워크 백엔드 (DNS 재바인딩 방지)."""

    def __init__(
        self,
        policy: AddressPolicy,
        resolver: Resolver = system_resolver,
        inner: AsyncNetworkBackend | None = None,
    ) -> None:
        self._policy = policy
        self._resolver = resolver
        self._inner = inner or AnyIOBackend()
        self.connected_ips: list[str] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        if not self._policy.is_port_allowed(port):
            raise SSRFError("허용되지 않은 포트로의 연결이 차단되었습니다.")
        addresses = await resolve_and_validate(host, port, self._policy, self._resolver)
        last_exc: Exception | None = None
        for ip in addresses[:4]:
            try:
                stream = await self._inner.connect_tcp(
                    ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
                continue
            self.connected_ips.append(ip)
            return stream
        assert last_exc is not None
        raise last_exc

    async def connect_unix_socket(self, *args, **kwargs) -> AsyncNetworkStream:  # pragma: no cover
        raise SSRFError("유닉스 소켓 연결은 허용되지 않습니다.")

    async def sleep(self, seconds: float) -> None:  # pragma: no cover
        await self._inner.sleep(seconds)


class _RedirectError(Exception):
    pass


def _cert_expiry(response: httpx.Response) -> datetime | None:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return None
    try:
        ssl_object = stream.get_extra_info("ssl_object")
        if ssl_object is None:
            return None
        cert = ssl_object.getpeercert()
        not_after = cert.get("notAfter") if cert else None
        if not not_after:
            return None
        return datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=UTC)
    except Exception:  # pragma: no cover - 방어적 처리
        logger.debug("TLS 인증서 정보를 읽지 못했습니다", exc_info=True)
        return None


def _describe_connect_error(exc: BaseException) -> tuple[str, str]:
    text = str(exc)
    cause = exc.__cause__ or exc.__context__
    if isinstance(cause, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in text:
        reason = getattr(cause, "verify_message", None) or text
        if "expired" in reason:
            return "tls", "TLS 인증서가 만료되었습니다."
        if "hostname" in reason or "Hostname mismatch" in reason:
            return "tls", "TLS 인증서의 호스트 이름이 일치하지 않습니다."
        if "self-signed" in reason or "self signed" in reason:
            return "tls", "자체 서명된 TLS 인증서입니다."
        return "tls", f"TLS 인증서 검증 실패: {reason[:200]}"
    if isinstance(cause, ssl.SSLError) or "SSL" in text:
        return "tls", "TLS 핸드셰이크에 실패했습니다."
    lowered = text.lower()
    if "refused" in lowered:
        return "connection", "연결이 거부되었습니다 (포트가 닫혀 있음)."
    if "unreachable" in lowered:
        return "connection", "네트워크에 도달할 수 없습니다."
    if "reset" in lowered:
        return "connection", "연결이 재설정되었습니다."
    return "connection", "서버에 연결할 수 없습니다."


class HttpChecker:
    def __init__(
        self,
        settings: Settings,
        *,
        policy: AddressPolicy | None = None,
        resolver: Resolver = system_resolver,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.settings = settings
        self.policy = policy or AddressPolicy.from_settings(settings.allowed_ports, settings.allowed_cidrs)
        self.resolver = resolver
        self.ssl_context = ssl_context or httpx.create_ssl_context(trust_env=True)
        self.proxy = settings.check_egress_proxy

    def _client(self, timeout: float) -> tuple[httpx.AsyncClient, SafeNetworkBackend | None]:
        backend: SafeNetworkBackend | None = None
        if self.proxy:
            # 프록시 모드: 연결 대상은 프록시뿐이며, 최종 DNS 해석·송신 필터링은 프록시가 수행합니다.
            transport = httpx.AsyncHTTPTransport(verify=self.ssl_context, proxy=self.proxy, retries=0)
        else:
            backend = SafeNetworkBackend(self.policy, self.resolver)
            transport = httpx.AsyncHTTPTransport(verify=self.ssl_context, retries=0)
            # 기본 연결 풀을 IP 고정 백엔드를 사용하는 풀로 교체합니다.
            transport._pool = httpcore.AsyncConnectionPool(
                ssl_context=self.ssl_context,
                max_connections=4,
                max_keepalive_connections=0,
                retries=0,
                network_backend=backend,
            )
        client = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": self.settings.check_user_agent, "Accept": "*/*"},
        )
        return client, backend

    async def check(self, target: CheckTarget) -> CheckOutcome:
        checked_at = utcnow()
        started = time.perf_counter()

        def elapsed_ms() -> int:
            return int((time.perf_counter() - started) * 1000)

        progress = {"redirects": 0}

        def fail(error_type: str, message: str, outcome: str = "down") -> CheckOutcome:
            return CheckOutcome(
                outcome=outcome,
                checked_at=checked_at,
                response_time_ms=elapsed_ms(),
                error_type=error_type,
                error_message=message[:500],
                redirect_count=progress["redirects"],
            )

        timeout = float(target.timeout_seconds)
        try:
            async with asyncio.timeout(timeout):
                return await self._run(target, checked_at, elapsed_ms, progress)
        except (TimeoutError, httpx.TimeoutException):
            return fail("timeout", f"{target.timeout_seconds:g}초 안에 응답이 없습니다 (타임아웃).")
        except DNSResolutionError:
            return fail("dns", "도메인 이름을 확인할 수 없습니다 (DNS 오류).")
        except SSRFError as exc:
            return fail("blocked", f"보안 정책에 의해 차단됨: {exc.message}")
        except _RedirectError as exc:
            return fail("redirect", str(exc))
        except httpx.ProxyError as exc:
            return fail("connection", f"송신 프록시를 통한 연결 실패: {str(exc)[:200]}")
        except httpx.ConnectError as exc:
            error_type, message = _describe_connect_error(exc)
            return fail(error_type, message)
        except (httpx.RemoteProtocolError, httpx.LocalProtocolError):
            return fail("protocol", "서버가 올바르지 않은 HTTP 응답을 보냈습니다.")
        except (httpx.ReadError, httpx.WriteError, httpx.NetworkError):
            return fail("connection", "응답을 읽는 중 연결이 끊어졌습니다.")
        except Exception:  # 검사기 자체 문제 → 측정 불가
            logger.exception("monitor %s 검사 중 내부 오류", target.monitor_id)
            return fail("internal", "검사기 내부 오류로 측정하지 못했습니다.", outcome="error")

    async def _run(self, target: CheckTarget, checked_at: datetime, elapsed_ms, progress: dict) -> CheckOutcome:
        client, backend = self._client(float(target.timeout_seconds))
        method = target.method if target.method in ("GET", "HEAD") else "GET"
        url = target.url
        redirects = 0
        tls_expires_at: datetime | None = None
        first_host = urlsplit(target.url).hostname
        async with client:
            while True:
                validated = validate_url(url, self.policy)
                if self.proxy and validated.ip_literal is None:
                    await self._best_effort_dns_check(validated.host, validated.port)
                request = client.build_request(method, validated.url)
                response = await client.send(request, stream=True)
                try:
                    if validated.scheme == "https" and tls_expires_at is None and validated.host == first_host:
                        tls_expires_at = _cert_expiry(response)

                    if target.follow_redirects and response.status_code in REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location:
                            raise _RedirectError("리다이렉트 응답에 Location 헤더가 없습니다.")
                        if redirects >= self.settings.check_max_redirects:
                            raise _RedirectError(
                                f"리다이렉트가 {self.settings.check_max_redirects}회를 초과했습니다."
                            )
                        next_url = str(response.url.join(location))
                        if urlsplit(next_url).scheme.lower() not in ("http", "https"):
                            raise _RedirectError("http/https 가 아닌 주소로의 리다이렉트는 따라가지 않습니다.")
                        redirects += 1
                        progress["redirects"] = redirects
                        url = next_url
                        continue

                    read = 0
                    limit = self.settings.check_max_response_bytes
                    if method != "HEAD":
                        async for chunk in response.aiter_raw():
                            read += len(chunk)
                            if read >= limit:
                                break
                    status = response.status_code
                    ok = status_matches(status, target.expected_status)
                    return CheckOutcome(
                        outcome="up" if ok else "down",
                        checked_at=checked_at,
                        status_code=status,
                        response_time_ms=elapsed_ms(),
                        error_type=None if ok else "status",
                        error_message=None
                        if ok
                        else f"예상하지 않은 HTTP 상태 코드 {status} (기대값: {target.expected_status})",
                        redirect_count=redirects,
                        tls_expires_at=tls_expires_at,
                        connected_ip=backend.connected_ips[-1] if backend and backend.connected_ips else None,
                    )
                finally:
                    await response.aclose()

    async def _best_effort_dns_check(self, host: str, port: int) -> None:
        try:
            await resolve_and_validate(host, port, self.policy, self.resolver)
        except DNSResolutionError:
            # 로컬 DNS 를 사용할 수 없는 환경: 프록시가 해석·필터링을 담당합니다.
            return
