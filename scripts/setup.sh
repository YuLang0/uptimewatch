#!/usr/bin/env bash
# UptimeWatch 한 번에 실행하기
#   ./scripts/setup.sh            → .env 준비(없으면 생성) → 이미지 빌드 → 전체 서비스 실행 → 상태 확인
# 필요: Docker 24+ (docker compose v2), curl, python3 또는 openssl
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
rand() {
  if command -v python3 >/dev/null 2>&1; then python3 -c "import secrets,sys;print(secrets.token_urlsafe(64)[:int(sys.argv[1])])" "$1"
  else openssl rand -hex "$1" | cut -c1-"$1"; fi
}

command -v curl >/dev/null || { echo "curl 이 필요합니다."; exit 1; }
command -v docker >/dev/null || { echo "Docker 가 필요합니다: https://docs.docker.com/engine/install/"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose v2 가 필요합니다."; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker 데몬이 실행 중이 아닙니다. (예: sudo systemctl start docker)"; exit 1; }

if [ ! -f .env ]; then
  say "1/3 .env 생성 (DB 비밀번호·SECRET_KEY 를 무작위로 채웁니다)"
  cp .env.example .env
  sed -i.bak "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand 32)|; s|^SECRET_KEY=.*|SECRET_KEY=$(rand 64)|" .env && rm -f .env.bak
  echo "   → .env 를 만들었습니다. 이메일 알림은 SMTP_* 를 채운 뒤 'docker compose up -d' 로 반영하세요."
else
  say "1/3 기존 .env 사용"
fi

say "2/3 이미지 빌드 및 실행 (처음에는 몇 분 걸립니다)"
docker compose up -d --build

say "3/3 상태 확인"
PORT=$(grep -E '^WEB_PORT=' .env | cut -d= -f2); PORT=${PORT:-8080}
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    docker compose ps --format 'table {{.Service}}\t{{.Status}}'
    URL=$(grep -E '^PUBLIC_BASE_URL=' .env | cut -d= -f2)
    say "완료! 브라우저에서 ${URL:-http://localhost:${PORT}} 에 접속해 회원가입하세요."
    echo "   로그: docker compose logs -f api worker   |   중지: docker compose stop   |   백업: ./scripts/backup.sh"
    exit 0
  fi
  sleep 2
done
echo "서비스가 응답하지 않습니다. 'docker compose ps' 와 'docker compose logs api worker' 를 확인하세요."
exit 1
