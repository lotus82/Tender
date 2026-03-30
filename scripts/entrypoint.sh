#!/usr/bin/env sh
# Точка входа контейнера приложения (бот и Celery worker).
# 1) Ожидание PostgreSQL по DATABASE_URL
# 2) Применение миграций Alembic (создание/обновление таблиц)
# 3) Запуск переданной команды (exec — процесс остаётся PID 1)

set -e

echo "[entrypoint] Шаг 1/3: проверка доступности PostgreSQL…"
python /app/scripts/wait_for_db.py

echo "[entrypoint] Шаг 2/3: alembic upgrade head (миграции схемы)…"
cd /app
alembic upgrade head

echo "[entrypoint] Шаг 3/3: запуск основного процесса: $*"
exec "$@"
