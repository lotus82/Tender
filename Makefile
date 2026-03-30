# Удобные команды для Docker Compose и резервного копирования.
# На Windows: установите GNU Make (Git Bash / Chocolatey) или вызывайте скрипты вручную.

COMPOSE ?= docker compose

.PHONY: up down logs backup restore

## Поднять стек (сборка образов, фон)
up:
	$(COMPOSE) up -d --build

## Остановить и удалить контейнеры (том postgres_data сохраняется)
down:
	$(COMPOSE) down

## Поток логов всех сервисов
logs:
	$(COMPOSE) logs -f

## Дамп БД в ./backups/tender_YYYYMMDD_HHMMSS.sql
backup:
	sh scripts/backup.sh

## Восстановление: make restore file=имя_файла.sql (файл должен лежать в ./backups/)
restore:
	@test -n "$(file)" || (echo "Укажите: make restore file=имя.sql" && exit 1)
	sh scripts/restore.sh "$(file)"
