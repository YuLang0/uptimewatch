#!/usr/bin/env bash
# E2E 용 백엔드 실행: 테스트 DB 초기화 → 작업자(백그라운드) → API
# 모의 대상 서버(127.0.0.1)만 검사할 수 있도록 CHECK_ALLOWED_CIDRS 를 루프백 1개로 한정합니다(E2E 전용).
set -euo pipefail
cd "$(dirname "$0")/../../backend"
export DATABASE_URL="postgresql+asyncpg://uptimewatch:uptimewatch@localhost:5432/uptimewatch_e2e"
export ENVIRONMENT=test SECRET_KEY=e2e-secret-key PUBLIC_BASE_URL=http://127.0.0.1:14173
export CHECK_ALLOWED_CIDRS=127.0.0.1/32 CHECK_ALLOWED_PORTS=
export MANUAL_CHECK_COOLDOWN_SECONDS=1 WORKER_TICK_SECONDS=0.5 TEST_NOTIFICATION_COOLDOWN_SECONDS=1
# 한 IP(127.0.0.1)에서 여러 테스트 계정을 만들므로 가입 빈도 제한만 완화
export REGISTER_RATE_LIMIT_PER_HOUR=1000
unset SMTP_HOST SMTP_FROM
PY=.venv/bin/python
$PY -m scripts.reset_e2e_db
$PY -m app.worker &
WORKER=$!
trap 'kill $WORKER 2>/dev/null || true' EXIT INT TERM
$PY -m uvicorn app.main:app --host 127.0.0.1 --port 18000 --log-level warning
