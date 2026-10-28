#!/usr/bin/env bash
# PostgreSQL 복원: ./scripts/restore.sh backups/uptimewatch_YYYYmmdd_HHMMSS.dump
# 복원 중에는 api/worker 를 멈추고, 끝나면 다시 시작합니다.
set -euo pipefail
cd "$(dirname "$0")/.."
FILE="${1:?복원할 백업 파일을 지정하세요}"
[ -f "$FILE" ] || { echo "파일 없음: $FILE"; exit 1; }
set -a; [ -f .env ] && . ./.env; set +a
read -r -p "현재 데이터베이스 내용을 '$FILE' 로 덮어씁니다. 계속할까요? [y/N] " ok
[ "$ok" = "y" ] || { echo "취소했습니다."; exit 1; }
docker compose stop api worker
docker compose exec -T db pg_restore -U "${POSTGRES_USER:-uptimewatch}" -d "${POSTGRES_DB:-uptimewatch}" \
  --clean --if-exists --no-owner --single-transaction < "$FILE"
docker compose run --rm migrate
docker compose start api worker
echo "복원 완료. 작업자가 재시작되며 밀린 검사를 분산 예약합니다."
