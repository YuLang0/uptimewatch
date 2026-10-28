# UptimeWatch 백엔드 (API · 작업자 · 마이그레이션 공용 이미지)
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
# 선택: TLS 를 가로채는 사내 프록시 환경이면 --secret id=extra_ca,src=<CA.pem> 로 CA 를 전달(이미지에 남지 않음)
RUN --mount=type=secret,id=extra_ca \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

# 비루트 사용자로 실행
RUN useradd --system --uid 10001 --home /app uptimewatch && chown -R uptimewatch /app
USER uptimewatch

EXPOSE 8000
# 기본 명령: API. 작업자는 compose 에서 `python -m app.worker` 로 실행합니다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
