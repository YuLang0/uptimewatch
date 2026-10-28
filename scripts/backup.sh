#!/usr/bin/env bash
# PostgreSQL 백업: ./scripts/backup.sh [출력 디렉터리]
# custom 형식(pg_dump -Fc)으로 저장하며 최근 14개만 보관합니다.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT_DIR="${1:-./backups}"
mkdir -p "$OUT_DIR"
set -a; [ -f .env ] && . ./.env; set +a
FILE="$OUT_DIR/uptimewatch_$(date +%Y%m%d_%H%M%S).dump"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-uptimewatch}" -d "${POSTGRES_DB:-uptimewatch}" -Fc > "$FILE"
echo "백업 완료: $FILE ($(du -h "$FILE" | cut -f1))"
ls -1t "$OUT_DIR"/uptimewatch_*.dump | tail -n +15 | xargs -r rm --
