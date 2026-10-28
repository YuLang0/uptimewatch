"""인증: Argon2id 비밀번호 해시, 서버 측 세션(해시 저장), CSRF 토큰."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User, UserSession

SESSION_COOKIE = "uw_session"
CSRF_COOKIE = "uw_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_hasher = PasswordHasher()  # argon2id 기본값
# 사용자 존재 여부를 응답 시간으로 추측하지 못하도록 더미 해시와 비교
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_for(session_token: str, settings: Settings) -> str:
    key = settings.secret_key.get_secret_value().encode()
    return hmac.new(key, f"csrf:{session_token}".encode(), hashlib.sha256).hexdigest()


async def create_session(db: AsyncSession, user: User, user_agent: str | None, settings: Settings) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(hours=settings.session_ttl_hours),
            last_seen_at=now,
            user_agent=(user_agent or "")[:200] or None,
        )
    )
    # 만료된 세션 정리
    await db.execute(delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at < now))
    return token


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다.")
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_token(token))
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "세션이 만료되었습니다. 다시 로그인하세요.")
    session, user = row
    if session.expires_at < now or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "세션이 만료되었습니다. 다시 로그인하세요.")

    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not hmac.compare_digest(sent, csrf_for(token, settings)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF 토큰이 올바르지 않습니다. 페이지를 새로고침하세요.")

    if (now - session.last_seen_at).total_seconds() > 300:
        session.last_seen_at = now
        await db.commit()
    request.state.session_token = token
    return user
