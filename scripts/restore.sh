#!/usr/bin/env sh
# Восстановление БД из SQL-дампа в ./backups/<имя_файла>.
# ВНИМАНИЕ: пересоздаётся схема public — все текущие данные в этой схеме будут удалены.
# Использование: sh scripts/restore.sh имя_файла.sql
# Запускать из корня репозитория.

set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

POSTGRES_USER="${POSTGRES_USER:-tender}"
POSTGRES_DB="${POSTGRES_DB:-tender}"

if [ "$#" -lt 1 ] || [ -z "$1" ]; then
  echo "Ошибка: укажите имя файла дампа в каталоге backups/." >&2
  echo "Пример: sh scripts/restore.sh tender_20260330_120000.sql" >&2
  exit 1
fi

FILE="$1"
# Запретить path traversal
case "$FILE" in
  *..*|*/*|\\*)
    echo "Ошибка: недопустимое имя файла." >&2
    exit 1
    ;;
esac

DUMP_PATH="backups/${FILE}"
if [ ! -f "${DUMP_PATH}" ]; then
  echo "Ошибка: файл не найден: ${DUMP_PATH}" >&2
  exit 1
fi

echo "=== Восстановление PostgreSQL из дампа ==="
echo "Файл: ${DUMP_PATH}"
echo "База: ${POSTGRES_DB}, пользователь: ${POSTGRES_USER}"
echo "Шаг 1: пересоздание схемы public (DROP SCHEMA … CASCADE)…"

docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 <<EOF
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
ALTER SCHEMA public OWNER TO "${POSTGRES_USER}";
GRANT ALL ON SCHEMA public TO "${POSTGRES_USER}";
GRANT ALL ON SCHEMA public TO public;
EOF

echo "Шаг 2: загрузка данных из SQL-файла…"
docker compose exec -T -i postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 < "${DUMP_PATH}"

echo "Готово: база восстановлена из ${FILE}"
echo "=== Конец восстановления ==="
