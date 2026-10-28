#!/usr/bin/env bash
# UptimeWatch 한 번에 실행하기
#   ./scripts/setup.sh                         → 로컬/내부망: http://localhost:8080
#   ./scripts/setup.sh --domain status.a.com   → 서버 배포: Caddy 로 HTTPS 자동 발급(https://status.a.com)
# 동작: .env 준비(없으면 생성, 비밀값 무작위) → 이미지 빌드 → 전체 서비스 실행 → 상태 확인
# 필요: Docker 24+ (docker compose v2), curl, python3 또는 openssl
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
usage() { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; }
rand() {
  if command -v python3 >/dev/null 2>&1; then python3 -c "import secrets,sys;print(secrets.token_urlsafe(64)[:int(sys.argv[1])])" "$1"
  else openssl rand -hex "$1" | cut -c1-"$1"; fi
}
# .env 의 KEY 값을 바꾸고, 없으면 추가
set_env() {
  if grep -qE "^$1=" .env; then
    sed -i.bak "s|^$1=.*|$1=$2|" .env && rm -f .env.bak
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}
get_env() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- || true; }

DOMAIN_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN_ARG="${2:-}"; shift 2 || { echo "--domain 뒤에 도메인을 입력하세요."; exit 1; } ;;
    --domain=*) DOMAIN_ARG="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "알 수 없는 옵션: $1"; usage; exit 1 ;;
  esac
done
if [ -n "$DOMAIN_ARG" ] && ! printf '%s' "$DOMAIN_ARG" | grep -qE '^([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$'; then
  echo "도메인 형식이 올바르지 않습니다: $DOMAIN_ARG (예: status.example.com, myname.duckdns.org)"; exit 1
fi

command -v curl >/dev/null || { echo "curl 이 필요합니다."; exit 1; }
command -v docker >/dev/null || { echo "Docker 가 필요합니다: https://docs.docker.com/engine/install/ (서버라면 sudo ./scripts/server-init.sh)"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose v2 가 필요합니다."; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker 에 접근할 수 없습니다. 데몬이 꺼져 있거나(sudo systemctl start docker), 방금 docker 그룹에 추가됐다면 로그아웃 후 다시 접속하세요."; exit 1; }

if [ ! -f .env ]; then
  say "1/3 .env 생성 (DB 비밀번호·SECRET_KEY 를 무작위로 채웁니다)"
  cp .env.example .env
  set_env POSTGRES_PASSWORD "$(rand 32)"
  set_env SECRET_KEY "$(rand 64)"
  echo "   → .env 를 만들었습니다. 이메일 알림은 SMTP_* 를 채운 뒤 'docker compose up -d' 로 반영하세요."
else
  say "1/3 기존 .env 사용"
fi

if [ -n "$DOMAIN_ARG" ]; then
  echo "   → HTTPS 배포 설정: $DOMAIN_ARG"
  set_env DOMAIN "$DOMAIN_ARG"
  set_env PUBLIC_BASE_URL "https://$DOMAIN_ARG"
  set_env COOKIE_SECURE true
  set_env WEB_BIND 127.0.0.1          # 평문 8080 은 서버 내부에서만
  set_env COMPOSE_PROFILES https      # 이후 모든 docker compose 명령에 Caddy 포함
fi
PUBLIC_URL=$(get_env PUBLIC_BASE_URL)
DOMAIN_SET=$(get_env DOMAIN)
if [ "$(get_env COMPOSE_PROFILES)" = "https" ]; then export COMPOSE_PROFILES=https; fi

say "2/3 이미지 빌드 및 실행 (처음에는 몇 분 걸립니다)"
docker compose up -d --build

say "3/3 상태 확인"
PORT=$(get_env WEB_PORT); PORT=${PORT:-8080}
ok=""
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [ -z "$ok" ]; then
  echo "서비스가 응답하지 않습니다. 'docker compose ps' 와 'docker compose logs api worker' 를 확인하세요."
  exit 1
fi
docker compose ps --format 'table {{.Service}}\t{{.Status}}'

if [ "${COMPOSE_PROFILES:-}" = "https" ]; then
  echo "   HTTPS 인증서 발급 확인 중 (최대 1분)…"
  https_ok=""
  for _ in $(seq 1 12); do
    if curl -fsS --max-time 5 "https://${DOMAIN_SET}/api/health" >/dev/null 2>&1; then https_ok=1; break; fi
    sleep 5
  done
  if [ -n "$https_ok" ]; then
    say "완료! 브라우저에서 ${PUBLIC_URL} 에 접속해 회원가입하세요."
  else
    say "서비스는 실행 중이지만 ${PUBLIC_URL} 에 아직 접속되지 않습니다."
    echo "   확인할 것: ① 도메인 A 레코드가 이 서버의 공인 IP 인지  ② 클라우드 방화벽(보안 목록)에서 TCP 80·443 허용"
    echo "              ③ sudo ./scripts/server-init.sh 실행 여부  ④ docker compose logs caddy"
  fi
  echo "   가입을 마쳤다면 다른 사람의 가입을 막으세요:"
  echo "     sed -i 's/^ALLOW_REGISTRATION=.*/ALLOW_REGISTRATION=false/' .env && docker compose up -d"
else
  say "완료! 브라우저에서 ${PUBLIC_URL:-http://localhost:${PORT}} 에 접속해 회원가입하세요."
fi
echo "   로그: docker compose logs -f api worker   |   중지: docker compose stop   |   백업: ./scripts/backup.sh"
