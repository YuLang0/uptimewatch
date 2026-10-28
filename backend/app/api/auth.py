from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, enforce, login_limiter, register_limiter
from app.config import Settings, get_settings
from app.db import get_db
from app.models import User, UserSession
from app.schemas import LoginIn, MeOut, RegisterIn, UserOut
from app.security.auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    create_session,
    csrf_for,
    get_current_user,
    hash_password,
    hash_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_auth_cookies(response: Response, token: str, settings: Settings) -> str:
    max_age = settings.session_ttl_hours * 3600
    csrf = csrf_for(token, settings)
    common = {"max_age": max_age, "secure": settings.cookie_secure, "samesite": "lax", "path": "/"}
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)
    return csrf


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.post("/register", response_model=MeOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeOut:
    if not settings.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "현재 회원가입이 비활성화되어 있습니다.")
    enforce(register_limiter(), client_ip(request), "가입 요청이 너무 많습니다. 잠시 후 다시 시도하세요.")
    email = body.email.lower()
    exists = await db.scalar(select(func.count()).select_from(User).where(User.email == email))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일입니다.")
    user = User(email=email, password_hash=hash_password(body.password), display_name=body.display_name.strip())
    db.add(user)
    await db.flush()
    token = await create_session(db, user, request.headers.get("user-agent"), settings)
    await db.commit()
    await db.refresh(user)
    csrf = _set_auth_cookies(response, token, settings)
    return MeOut(user=UserOut.model_validate(user), csrf_token=csrf)


@router.post("/login", response_model=MeOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeOut:
    email = body.email.lower()
    enforce(
        login_limiter(),
        f"{client_ip(request)}:{email}",
        "로그인 시도가 너무 많습니다. 15분 후 다시 시도하세요.",
    )
    user = await db.scalar(select(User).where(User.email == email))
    if not verify_password(user.password_hash if user else None, body.password) or not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다.")
    token = await create_session(db, user, request.headers.get("user-agent"), settings)
    await db.commit()
    csrf = _set_auth_cookies(response, token, settings)
    return MeOut(user=UserOut.model_validate(user), csrf_token=csrf)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    token = request.state.session_token
    await db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
    await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookies(response)
    return response


@router.get("/me", response_model=MeOut)
async def me(
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> MeOut:
    return MeOut(user=UserOut.model_validate(user), csrf_token=csrf_for(request.state.session_token, settings))
