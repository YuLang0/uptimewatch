from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import auth, monitors, notifications, overview, status_pages
from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

FIELD_LABELS = {
    "email": "이메일",
    "password": "비밀번호",
    "display_name": "이름",
    "name": "이름",
    "description": "설명",
    "url": "URL",
    "method": "요청 방식",
    "interval_seconds": "확인 주기",
    "timeout_seconds": "타임아웃",
    "expected_status": "기대 상태 코드",
    "failure_threshold": "연속 실패 기준",
    "recovery_threshold": "복구 기준",
    "slug": "주소(slug)",
    "title": "제목",
    "email_to": "수신 이메일",
    "email_cooldown_minutes": "중복 알림 제한 시간",
    "reminder_interval_minutes": "재알림 간격",
    "tls_warning_days": "인증서 만료 경고",
}


def _translate(error: dict) -> str:
    field = str(error.get("loc", ["", ""])[-1])
    label = FIELD_LABELS.get(field, field)
    msg = error.get("msg", "")
    ctx = error.get("ctx") or {}
    etype = error.get("type", "")
    if msg.startswith("Value error, "):
        return msg.removeprefix("Value error, ")
    if etype == "string_too_short":
        return f"{label}은(는) 최소 {ctx.get('min_length')}자 이상이어야 합니다."
    if etype == "string_too_long":
        return f"{label}은(는) 최대 {ctx.get('max_length')}자까지 입력할 수 있습니다."
    if etype in ("greater_than_equal", "less_than_equal"):
        bound = ctx.get("ge", ctx.get("le"))
        return f"{label} 값이 허용 범위를 벗어났습니다 (경계값 {bound})."
    if etype == "missing":
        return f"{label}을(를) 입력하세요."
    if "email" in etype or field in ("email", "email_to"):
        return "올바른 이메일 주소를 입력하세요."
    if etype in ("int_parsing", "int_type"):
        return f"{label}은(는) 숫자여야 합니다."
    if etype == "literal_error":
        return f"{label} 값이 올바르지 않습니다."
    return f"{label}: {msg}"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        # CSRF 1차 방어: 브라우저가 보낸 상태 변경 요청의 Origin 이 허용 목록에 없으면 거부
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") not in settings.allowed_origins:
                return JSONResponse({"detail": "허용되지 않은 출처(Origin)의 요청입니다."}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.is_production and settings.secret_key.get_secret_value().startswith("dev-insecure"):
        raise RuntimeError("운영 환경에서는 SECRET_KEY 를 반드시 설정하세요.")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await dispose_engine()

    app = FastAPI(
        title="UptimeWatch API",
        lifespan=lifespan,
        version="1.0.0",
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    app.add_middleware(SecurityHeadersMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        messages = [_translate(e) for e in errors]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": messages[0] if messages else "입력값이 올바르지 않습니다.", "errors": messages},
        )

    # 외부 감시 서비스(UptimeRobot 등)는 HEAD 로 확인하는 경우가 많아 GET·HEAD 모두 받습니다.
    @app.api_route("/api/health", methods=["GET", "HEAD"], tags=["system"])
    async def health() -> dict:
        try:
            async with get_sessionmaker()() as db:
                await db.execute(text("SELECT 1"))
            return {"status": "ok"}
        except Exception:
            return JSONResponse({"status": "error"}, status_code=503)

    @app.api_route("/api/health/worker", methods=["GET", "HEAD"], tags=["system"])
    async def health_worker() -> dict:
        """검사 작업자의 하트비트가 최근에 있었는지. 멈췄으면 503 (상세 정보는 노출하지 않음)."""
        try:
            async with get_sessionmaker()() as db:
                status_ = (await overview.worker_status(db, settings))["status"]
        except Exception:
            return JSONResponse({"status": "error"}, status_code=503)
        if status_ != "ok":
            return JSONResponse({"status": status_}, status_code=503)
        return {"status": "ok"}

    for module in (auth, monitors, overview, notifications):
        app.include_router(module.router)
    app.include_router(status_pages.router)
    app.include_router(status_pages.public_router)
    return app


app = create_app()
