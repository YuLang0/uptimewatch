"""SSRF(서버 측 요청 위조) 방어.

방어 계층
1. URL 정책: http/https 만, 사용자 인증정보(user:pass@) 금지, 허용 포트만,
   단일 라벨/내부용 도메인 금지,
   숫자·16진수 형태의 비표준 IP 표기 금지.
2. 주소 정책: DNS 로 해석된 **모든** 주소가 공인(global) 주소여야 합니다. 루프백·사설·링크로컬·CGNAT·
   메타데이터(169.254.169.254, fd00:ec2::254)·멀티캐스트·예약·문서용·IPv4 매핑/NAT64/6to4/Teredo 대역은 차단합니다.
3. 연결 고정(pinning): 검증한 IP 로 직접 TCP 연결합니다(app.services.checker.SafeNetworkBackend).
   DNS 를 두 번 조회하지 않으므로 DNS 재바인딩(TOCTOU)이 불가능합니다.
   TLS SNI/인증서 검증은 원래 호스트명으로 수행됩니다.
4. 리다이렉트: 자동 추적을 끄고, 매 홉마다 1~3 단계를 다시 적용합니다.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[list[str]]]

MAX_URL_LENGTH = 2048

_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        # IPv4
        "0.0.0.0/8",  # "this" network
        "10.0.0.0/8",  # 사설
        "100.64.0.0/10",  # CGNAT
        "127.0.0.0/8",  # 루프백
        "169.254.0.0/16",  # 링크 로컬 + 클라우드 메타데이터(169.254.169.254)
        "172.16.0.0/12",  # 사설
        "192.0.0.0/24",  # IETF 프로토콜 할당
        "192.0.2.0/24",  # TEST-NET-1
        "192.88.99.0/24",  # 6to4 릴레이
        "192.168.0.0/16",  # 사설
        "198.18.0.0/15",  # 벤치마크
        "198.51.100.0/24",  # TEST-NET-2
        "203.0.113.0/24",  # TEST-NET-3
        "224.0.0.0/4",  # 멀티캐스트
        "240.0.0.0/4",  # 예약 + 브로드캐스트
        # IPv6
        "::/128",  # 미지정
        "::1/128",  # 루프백
        "::ffff:0:0/96",  # IPv4 매핑
        "::/96",  # IPv4 호환(폐기)
        "64:ff9b::/96",  # NAT64
        "64:ff9b:1::/48",  # 로컬 NAT64
        "100::/64",  # 폐기(discard)
        "2001::/23",  # IETF 프로토콜(Teredo 포함)
        "2001:db8::/32",  # 문서용
        "2002::/16",  # 6to4
        "fc00::/7",  # 고유 로컬(ULA, AWS fd00:ec2::254 포함)
        "fe80::/10",  # 링크 로컬
        "fec0::/10",  # 사이트 로컬(폐기)
        "ff00::/8",  # 멀티캐스트
    )
]

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata",
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
    "instance-data.ec2.internal",
    "kubernetes.default",
    "host.docker.internal",
    "gateway.docker.internal",
}

_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".localdomain",
    ".internal",
    ".intranet",
    ".lan",
    ".home",
    ".home.arpa",
    ".corp",
    ".private",
    ".svc",
    ".cluster.local",
    ".in-addr.arpa",
    ".ip6.arpa",
    ".onion",
)

_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_NUMERIC_LABEL_RE = re.compile(r"^(0x[0-9a-f]*|[0-9]+)$")


class SSRFError(Exception):
    """정책 위반으로 요청이 차단됨."""

    def __init__(self, message: str, code: str = "blocked") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class InvalidURLError(SSRFError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_url")


class DNSResolutionError(Exception):
    """도메인 이름을 해석할 수 없음 (NXDOMAIN, 타임아웃 등)."""


@dataclass(frozen=True)
class AddressPolicy:
    allowed_ports: frozenset[int] | None = frozenset({80, 443, 8080, 8443})
    # 명시적 예외(테스트·모의 서버 전용). 운영 환경에서는 비워 두세요.
    allowed_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = field(default_factory=tuple)

    @classmethod
    def from_settings(cls, ports: frozenset[int] | None, cidrs: Iterable[str]) -> AddressPolicy:
        return cls(
            allowed_ports=ports,
            allowed_networks=tuple(ipaddress.ip_network(c, strict=False) for c in cidrs),
        )

    def _explicitly_allowed(self, ip: IPAddress) -> bool:
        return any(ip.version == net.version and ip in net for net in self.allowed_networks)

    def is_ip_allowed(self, ip: IPAddress) -> bool:
        if self._explicitly_allowed(ip):
            return True
        if isinstance(ip, ipaddress.IPv6Address):
            mapped = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
            if mapped is not None:
                # 내장된 IPv4 를 기준으로 평가하되, 매핑 형식 자체도 아래에서 차단됩니다.
                if not self.is_ip_allowed(mapped):
                    return False
        if any(ip.version == net.version and ip in net for net in _BLOCKED_NETWORKS):
            return False
        if (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
        return True

    def is_port_allowed(self, port: int) -> bool:
        return self.allowed_ports is None or port in self.allowed_ports


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    scheme: str
    host: str  # IDNA(ASCII) 소문자. IPv6 는 대괄호 없이.
    port: int
    ip_literal: IPAddress | None


def parse_ip_literal(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None


def validate_url(raw: str, policy: AddressPolicy) -> ValidatedURL:
    """URL 형식·정책을 검증하고 정규화된 URL 을 반환합니다(DNS 조회 없음)."""
    if not isinstance(raw, str):
        raise InvalidURLError("URL 이 올바르지 않습니다.")
    url = raw.strip()
    if not url:
        raise InvalidURLError("URL 을 입력하세요.")
    if len(url) > MAX_URL_LENGTH:
        raise InvalidURLError(f"URL 은 {MAX_URL_LENGTH}자를 넘을 수 없습니다.")
    if any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in url) or "\\" in url:
        raise InvalidURLError("URL 에 공백·제어 문자·역슬래시를 사용할 수 없습니다.")

    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise InvalidURLError("URL 형식이 올바르지 않습니다.") from exc

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise InvalidURLError("http:// 또는 https:// 주소만 등록할 수 있습니다.")
    if not parts.netloc:
        raise InvalidURLError("호스트가 없는 URL 입니다.")
    if "@" in parts.netloc:
        raise InvalidURLError("URL 에 사용자 이름·비밀번호를 포함할 수 없습니다. 비밀정보는 저장하지 않습니다.")

    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidURLError("포트 번호가 올바르지 않습니다.") from exc
    if port is None:
        port = 443 if scheme == "https" else 80
    if not 1 <= port <= 65535:
        raise InvalidURLError("포트 번호가 올바르지 않습니다.")
    if not policy.is_port_allowed(port):
        allowed = ", ".join(str(p) for p in sorted(policy.allowed_ports or []))
        raise SSRFError(f"허용되지 않은 포트입니다. 허용 포트: {allowed}")

    hostname = (parts.hostname or "").rstrip(".")
    if not hostname:
        raise InvalidURLError("호스트가 없는 URL 입니다.")

    ip = parse_ip_literal(hostname)
    if ip is not None:
        if "%" in hostname:
            raise SSRFError("IPv6 영역(zone) 식별자는 허용되지 않습니다.")
        if not policy.is_ip_allowed(ip):
            raise SSRFError("사설·루프백·링크 로컬·메타데이터 등 내부 주소는 검사할 수 없습니다.")
        host = ip.compressed
    else:
        try:
            host = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise InvalidURLError("도메인 이름이 올바르지 않습니다.") from exc
        _validate_hostname(host)

    netloc_host = f"[{host}]" if ip is not None and ip.version == 6 else host
    default_port = 443 if scheme == "https" else 80
    netloc = netloc_host if port == default_port else f"{netloc_host}:{port}"
    path = parts.path or "/"
    normalized = urlunsplit((scheme, netloc, path, parts.query, ""))
    return ValidatedURL(url=normalized, scheme=scheme, host=host, port=port, ip_literal=ip)


def _validate_hostname(host: str) -> None:
    if len(host) > 253:
        raise InvalidURLError("도메인 이름이 너무 깁니다.")
    labels = host.split(".")
    if len(labels) < 2:
        raise SSRFError("단일 이름 호스트(예: intranet, db)는 검사할 수 없습니다. 공개 도메인을 입력하세요.")
    for label in labels:
        if not _LABEL_RE.match(label):
            raise InvalidURLError("도메인 이름에 허용되지 않는 문자가 있습니다.")
    if all(_NUMERIC_LABEL_RE.match(label) for label in labels) or _NUMERIC_LABEL_RE.match(labels[-1]):
        raise SSRFError("비표준 숫자 IP 표기(예: 127.1, 0x7f.1)는 허용되지 않습니다.")
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise SSRFError("내부용 호스트 이름은 검사할 수 없습니다.")


async def system_resolver(host: str, port: int) -> list[str]:
    """시스템 리졸버(getaddrinfo)로 주소 목록을 얻습니다."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise DNSResolutionError(str(exc)) from exc
    addresses: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr = str(sockaddr[0]).split("%", 1)[0]
        if addr not in addresses:
            addresses.append(addr)
    return addresses


async def resolve_and_validate(
    host: str, port: int, policy: AddressPolicy, resolver: Resolver = system_resolver
) -> list[str]:
    """호스트를 해석하고 모든 주소가 허용되는지 확인합니다. 하나라도 내부 주소면 차단합니다."""
    literal = parse_ip_literal(host)
    if literal is not None:
        if not policy.is_ip_allowed(literal):
            raise SSRFError("내부 주소로의 연결이 차단되었습니다.")
        return [literal.compressed]

    addresses = await resolver(host, port)
    if not addresses:
        raise DNSResolutionError("주소 레코드가 없습니다.")
    validated: list[str] = []
    for addr in addresses:
        ip = parse_ip_literal(addr)
        if ip is None or not policy.is_ip_allowed(ip):
            raise SSRFError("도메인이 사설·루프백·메타데이터 등 내부 주소로 해석되어 차단되었습니다.")
        validated.append(ip.compressed)
    return validated
