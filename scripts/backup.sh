#!/usr/bin/env sh
# Резервное копирование БД PostgreSQL из контейнера в каталог ./backups (на хосте).
# Запускать из корня репозитория, где лежит docker-compose.yml.

set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

POSTGRES_USER="${POSTGRES_USER:-tender}"
POSTGRES_DB="${POSTGRES_DB:-tender}"

mkdir -p backups
TS=$(date +%Y%m%d_%H%M%S)
OUT="backups/tender_${TS}.sql"

echo "=== Резервное копирование PostgreSQL ==="
echo "Пользователь БД: ${POSTGRES_USER}, база: ${POSTGRES_DB}"
echo "Файл дампа: ${OUT}"
echo "Выполняется pg_dump внутри контейнера postgres…"

docker compose exec -T postgres \
  pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  --no-owner --format=plain \
  > "${OUT}"

echo "Готово: дамп сохранён в ${OUT}"
echo "=== Конец резервного копирования ==="
