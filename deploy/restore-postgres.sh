#!/usr/bin/env sh
set -eu

if [ "${1:-}" = "" ]; then
  echo "Uso: sh deploy/restore-postgres.sh caminho/do/backup.sql"
  exit 1
fi

docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T db \
  psql -U "${POSTGRES_USER:-dash_user}" "${POSTGRES_DB:-dash_atestados}" \
  < "$1"

echo "Restore concluido a partir de $1"
