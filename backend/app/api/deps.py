from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException, Request, status

from app.config import get_settings
from app.security.rate_limit import SlidingWindowLimiter
from app.security.ssrf import Resolver, system_resolver


def get_resolver() -> Resolver:
    """DNS 리졸버 의존성 (테스트에서 가짜 리졸버로 교체)."""
    return system_resolver


def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers 가 신뢰하는 리버스 프록시의 X-Forwarded-For 를 반영합니다.
    return request.client.host if request.client else "unknown"


@lru_cache
def login_limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(get_settings().login_rate_limit_per_15min, 15 * 60)


@lru_cache
def register_limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(get_settings().register_rate_limit_per_hour, 60 * 60)


@lru_cache
def public_limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(120, 60)


@lru_cache
def test_notification_limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(1, get_settings().test_notification_cooldown_seconds)


def enforce(limiter: SlidingWindowLimiter, key: str, message: str) -> None:
    if not limiter.hit(key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            message,
            headers={"Retry-After": str(limiter.retry_after(key))},
        )


def reset_limiters() -> None:
    for factory in (login_limiter, register_limiter, public_limiter, test_notification_limiter):
        factory().reset()
