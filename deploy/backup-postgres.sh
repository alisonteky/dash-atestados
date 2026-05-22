#!/usr/bin/env sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T db \
  pg_dump -U "${POSTGRES_USER:-dash_user}" "${POSTGRES_DB:-dash_atestados}" \
  > "$BACKUP_DIR/dash-atestados-$TIMESTAMP.sql"

echo "Backup criado em $BACKUP_DIR/dash-atestados-$TIMESTAMP.sql"
