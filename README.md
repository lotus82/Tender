# AI Tender Agent

Агент для анализа тендерной документации (44‑ФЗ, 223‑ФЗ) на Python. Проект строится по **гексагональной архитектуре (порты и адаптеры)**: ядро и сценарии использования не зависят от Telegram, конкретной БД в коде домена или от выбранного LLM‑провайдера.

## Документация (единый источник правды)

Все ключевые сведения об архитектуре, запуске и границах слоёв фиксируются **только в этом файле** (`README.md`). При изменении структуры или правил интеграции обновляйте соответствующие разделы здесь, а не расползайтесь по отдельным markdown‑файлам.

## Архитектура

### Слои

| Каталог | Назначение |
|--------|------------|
| `src/domain/` | Сущности и доменные исключения (`FileDownloadError`, `DocumentParsingError`, `LlmAnalysisError` и др.). |
| `src/application/ports/` | **Порты** — `INotificationPort`, `IFileProviderPort`, `ILLMPort`, **`ITenderRequestRepository`**. |
| `src/application/services/` | Парсинг документов в Markdown (`parsers.py`), без Telegram/SQLAlchemy. |
| `src/application/use_cases/` | **`AnalyzeTenderUseCase`** — порты, парсинг и **репозиторий заявок** (без прямого SQLAlchemy). |
| `src/infrastructure/adapters/` | **Адаптеры** — Telegram, Gemini, **`postgres_repository.py`** (`PostgresTenderRequestRepository`). |
| `src/infrastructure/db/` | Подключение к БД, SQLAlchemy `Base`, async engine и сессии (`database.py`), ORM‑модели (`models.py`). |
| `src/infrastructure/config/` | Настройки через Pydantic `BaseSettings` (в т.ч. `GEMINI_MODEL`, `GEMINI_TIMEOUT_MS`). |
| `src/presentation/telegram/` | Точка входа aiogram, middleware (агрегация альбомов), хендлеры; постановка задачи `process_tender_task.delay(...)`. |
| `src/worker/` | `celery_app.py` (брокер Redis из Settings, autodiscover задач), `tasks.py` (`process_tender_task`). |
| `alembic/` | Миграции схемы БД (async, `DATABASE_URL`). |
| `scripts/` | `entrypoint.sh` (ожидание БД + `alembic upgrade head`), `wait_for_db.py`, `backup.sh`, `restore.sh`. |
| `backups/` | Каталог дампов SQL на хосте (том `./backups` смонтирован в `postgres:/backups`). |

### Поток обработки заявки (сквозной, с персистенцией)

1. Пользователь отправляет файлы и запрос → **хендлер** отвечает сразу и вызывает **`process_tender_task.delay(..., username=..., display_name=...)`** (Celery, JSON).
2. **Воркер** выполняет **`asyncio.run`**: открывает **`AsyncSession`**, создаёт **`PostgresTenderRequestRepository(session)`**, **`aiogram.Bot`**, остальные адаптеры и **`AnalyzeTenderUseCase(..., tender_requests=repo)`**; после успешного сценария делает **`session.commit()`**.
3. **Сценарий** (`analyze_tender.py`) работает **только с портами**: сохраняет заявку со статусом **`PROCESSING`**, скачивает файлы, парсит Markdown, вызывает **`ILLMPort.analyze`**, при успехе обновляет статус на **`COMPLETED`** и пишет **`result_text`** (ответ LLM), затем **`INotificationPort.send_message`**. При ошибке — **`FAILED`**, в **`result_text`** причина, пользователю — локализованное сообщение.
4. Ошибки парсинга, загрузки и LLM маппятся в понятные пользователю сообщения; доменные исключения могут порождаться в адаптерах.

### Машина состояний заявки (`TenderRequestStatus`)

| Значение (Enum) | Смысл | Где выставляется |
|-----------------|--------|-------------------|
| **`RECEIVED`** | Заявка принята на уровне UI/доменного черновика (например, в хендлере до очереди). | Презентация / клиентский код |
| **`PROCESSING`** | Идёт загрузка файлов и анализ. | Первая запись в БД из **`AnalyzeTenderUseCase.execute`** |
| **`COMPLETED`** | Успешно; в **`result_text`** хранится ответ LLM. | После успешного `analyze` |
| **`FAILED`** | Ошибка; в **`result_text`** — техническая причина / исключение. | Любая обработанная ошибка сценария |

В доменной сущности **`TenderRequest`** также есть **`created_at`** и опциональный **`result_text`**; в БД строка **`request_logs`** дублирует статус и результат.

### Репозиторий (паттерн Repository)

- **Порт** `ITenderRequestRepository` (`application/ports/repository.py`): `save`, `get_by_id`, `update_status` — **асинхронные** методы, без SQLAlchemy в сигнатурах.
- **Адаптер** `PostgresTenderRequestRepository` (`infrastructure/adapters/postgres_repository.py`): одна **`AsyncSession`** на выполнение задачи; маппинг **`TenderRequest`** ↔ **`RequestLog`** + upsert **`User`** по `telegram_user_id`.
- **Use case** не импортирует ORM и не открывает сессии — зависимость только от порта.

### Парсеры (`application/services/parsers.py`)

| Тип (детекция) | Библиотека | Таблицы в Markdown |
|----------------|------------|-------------------|
| PDF | `pdfplumber` | `extract_tables()` → строки `| … |` и разделитель `|---|` |
| DOCX | `python-docx` | обход блоков документа; таблицы через общую функцию сборки Markdown |
| XLSX | `pandas` + `openpyxl` | `DataFrame.to_markdown()` (нужен пакет **`tabulate`**) |
| JPEG/PNG (и попытка для неизвестного типа) | `Pillow` + `pytesseract` | языки `rus+eng` |

### Как достигается независимость от Telegram

- Прикладной и доменный слой зависят только от **абстракций** в `application/ports/`. Например, после обработки документа воркер вызывает `INotificationPort.send_message(user_id, text)` и не импортирует `aiogram` внутри use case.
- Отправка в Telegram — это **адаптер** в `infrastructure/adapters/` (`TelegramNotificationAdapter` в `telegram_notifier.py`), который реализует порт и внутри себя использует `aiogram.Bot`.
- Смена канала (веб‑API, другой мессенджер) сводится к новому адаптеру и настройке внедрения зависимостей, без правок сценариев в `use_cases/`.

Направление зависимостей: **инфраструктура и представление → приложение → домен**. Домен никуда «наружу» не смотрит.

### Модели базы данных

ORM описаны в `src/infrastructure/db/models.py` (таблицы **`users`** и **`request_logs`**):

- **`User`** — пользователь канала: уникальный `telegram_user_id`, необязательные `username`, имя/фамилия, `created_at`. Связь один‑ко‑многим с журналом заявок.
- **`RequestLog`** — заявка: `user_id`, строковый **`status`** (значения enum домена), **`query_text`**, nullable **`result_text`** (ответ LLM или текст ошибки), **`created_at`**.

**Схема создаётся и эволюционирует через Alembic.** В Docker при каждом старте **`bot`** и **`worker`** скрипт **`scripts/entrypoint.sh`** ждёт готовности PostgreSQL (`wait_for_db.py` + `DATABASE_URL`), выполняет **`alembic upgrade head`**, затем запускает процесс бота или Celery — **таблицы на новом хосте создаются автоматически**, отдельный ручной шаг миграций не требуется. Вспомогательная **`init_db()`** в `database.py` оставлена только для локальных экспериментов без Alembic.

### Миграции Alembic

- Конфиг: **`alembic.ini`** в корне; скрипты — **`alembic/versions/`**. В **`alembic/env.py`** подключается **`DATABASE_URL`**, в `sys.path` добавляется **`src`**, `target_metadata = Base.metadata`, импортируются модели из `infrastructure.db.models` для **autogenerate**.
- Начальная ревизия: **`0001_initial_schema`** (таблицы `users`, `request_logs` с `result_text`).
- **Повторный прогон** `alembic upgrade head` у бота и воркера безопасен: Alembic использует блокировки; оба контейнера могут стартовать параллельно.

**Ручной запуск миграций** (если нужен без перезапуска приложения):

```bash
docker compose exec worker sh -lc "cd /app && alembic upgrade head"
```

**Новая ревизия после изменения моделей** (на хосте с доступом к БД):

```bash
set PYTHONPATH=src
set DATABASE_URL=postgresql+asyncpg://tender:tender@localhost:5432/tender
alembic revision --autogenerate -m "описание изменений"
alembic upgrade head
```

В Linux/macOS: `export` вместо `set`. Закоммитьте файл в `alembic/versions/` и задеплойте образ; при следующем старте контейнеров entrypoint снова выполнит **`upgrade head`**.

### Агрегация альбомов Telegram (`MediaGroupMiddleware`)

Telegram не присылает «одно сообщение с десятью файлами»: **альбом** — это серия сообщений с общим `media_group_id`. Без доработки бот обработал бы каждое вложение отдельно.

`MediaGroupMiddleware` (`src/presentation/telegram/middlewares/media_group.py`):

1. Сообщения **без** `media_group_id` сразу преобразуются в список доменных `TenderDocument` и текст запроса (`text` / `caption`) и передаются в хендлер.
2. Сообщения **с** `media_group_id` складываются в буфер по ключу группы. При каждом новом элементе альбома предыдущий таймер **отменяется** и запускается новый цикл ожидания **`asyncio.sleep(3)`** (debounce по последнему сообщению). По истечении паузы все части сортируются по `message_id`, вложения объединяются, текст запроса берётся из подписи/текста сообщений группы, и **один раз** вызывается следующий обработчик в цепочке с уже заполненными `tender_documents` и `user_query_text`.

Таким образом, хендлер получает единый список файлов и один ответ пользователю, что соответствует бизнес‑правилу «до 10 файлов в одной заявке».

## Развёртывание (VPS, прод, новый хост)

1. Установите **Docker** и **Docker Compose v2**, склонируйте репозиторий.
2. Создайте `.env` с реальными **`TELEGRAM_BOT_TOKEN`**, **`GEMINI_API_KEY`** и при необходимости скорректируйте **`DATABASE_URL`** / пароли PostgreSQL в `docker-compose.yml`. Если хост находится в регионе, где официальный Gemini API недоступен (в т.ч. ответы вида **400 FAILED_PRECONDITION**), задайте **`GEMINI_BASE_URL`** — базовый URL вашего HTTP‑прокси (например Cloudflare Worker), который проксирует путь **`/v1beta/models/...:generateContent`** к Google; воркер собирает запрос через **`aiohttp`** к `{GEMINI_BASE_URL}/v1beta/models/{GEMINI_MODEL}:generateContent`. Без переменной или при пустом значении используется **`https://generativelanguage.googleapis.com`**.
3. Из корня проекта выполните **`make up`** или:

   ```bash
   docker compose up -d --build
   ```

4. Сервис **`postgres`** поднимается с **healthcheck** (`pg_isready` + тестовый `SELECT 1`); **`bot`** и **`worker`** ждут `service_healthy`, затем **entrypoint** ждёт TCP к БД по `DATABASE_URL`, прогоняет **`alembic upgrade head`** и только после этого стартует приложение — **схема БД создаётся/обновляется без ручных команд**.

Каталог **`./backups`** на хосте смонтирован в контейнер PostgreSQL как **`/backups`** (удобно класть файлы для восстановления или копировать дампы с сервера). Данные кластера лежат в именованном томе **`postgres_data`**.

### Makefile (операции из корня репозитория)

| Цель | Действие |
|------|----------|
| `make up` | `docker compose up -d --build` |
| `make down` | `docker compose down` |
| `make logs` | `docker compose logs -f` |
| `make backup` | `sh scripts/backup.sh` — дамп в `./backups/tender_*.sql` |
| `make restore file=имя.sql` | `sh scripts/restore.sh имя.sql` — файл должен лежать в **`./backups/`** |

На Windows без **GNU Make** вызывайте те же команды вручную или через Git Bash.

## Запуск через Docker Compose (детали)

1. **Файл `.env` не обязателен** для первого знакомства: в `docker-compose.yml` заданы значения по умолчанию.
2. Для **боевого** режима заполните `.env` (шаблон — `.env.example`).
3. Поднимаются четыре сервиса:

- **`postgres`** — PostgreSQL 16, том **`postgres_data`**, примонтированный **`./backups:/backups`**, усиленный **healthcheck**.
- **`redis`** — брокер и бэкенд результатов Celery (со своим healthcheck).
- **`bot`** — `ENTRYPOINT` → **`scripts/entrypoint.sh`**, затем `python -m presentation.telegram.main`.
- **`worker`** — тот же entrypoint, затем `celery -A worker.celery_app worker --loglevel=info`.

Образ один (`Dockerfile`, `python:3.11-slim`): Poppler, Tesseract, код, Alembic, **`scripts/entrypoint.sh`** и **`wait_for_db.py`**.

## Резервное копирование и восстановление

### Резервная копия

- Убедитесь, что стек запущен (`make up`).
- Выполните **`make backup`** или **`sh scripts/backup.sh`** из корня репозитория.
- В каталоге **`./backups/`** появится файл вида **`tender_YYYYMMDD_HHMMSS.sql`** (логи на русском — в самом скрипте).

Переменные **`POSTGRES_USER`** и **`POSTGRES_DB`** на хосте при необходимости переопределите перед вызовом (по умолчанию **`tender`** / **`tender`**, как в Compose).

### Восстановление

- Положите файл дампа в **`./backups/`** (или используйте уже созданный там файл).
- Выполните **`make restore file=имя_файла.sql`** или **`sh scripts/restore.sh имя_файла.sql`**.
- Скрипт **пересоздаёт схему `public`** (все текущие данные в ней удаляются), затем заливает SQL из файла. В консоль выводятся пояснения на русском.

После восстановления при необходимости перезапустите **`bot`** и **`worker`**.

### Аварийное копирование с сервера

Файлы в **`./backups`** на диске хоста доступны без входа в контейнер; при монтировании тома на VPS настройте отдельный off-site бэкап этого каталога (rsync, object storage и т.д.).

## Локальная разработка (без Docker)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set PYTHONPATH=src
python -m presentation.telegram.main
```

На Linux/macOS: `export PYTHONPATH=src`. Нужны установленные Tesseract и Poppler, если планируете парсинг на машине разработчика. Для полного цикла параллельно запустите PostgreSQL, Redis, выполните **`alembic upgrade head`**, Celery worker (см. выше).

### Локальный запуск только воркера (без Docker)

Из корня проекта, с `PYTHONPATH=src` и заполненным `.env`:

```bash
celery -A worker.celery_app worker --loglevel=info
```

## Переменные окружения

См. `.env.example`. Класс настроек: `src/infrastructure/config/settings.py` (`Settings` / `get_settings()`). Дополнительно: **`WELCOME_MESSAGE`** (текст `/start`), **`LLM_TEMPERATURE`**, **`PROCESSING_TIMEOUT_SECONDS`** (мягкий лимит Celery на задачу `process_tender`; жёсткий лимит = +15 с), **`GEMINI_MODEL`** (по умолчанию `gemini-2.5-flash`; для сложных отчётов можно `gemini-2.5-pro`), **`GEMINI_TIMEOUT_MS`** (миллисекунды HTTP к Gemini), **`GEMINI_BASE_URL`** (опционально — прокси для обхода гео‑блокировки; см. раздел развёртывания). Загрузка файлов: сначала `.env.example`, затем `.env`.

## Текущее состояние (этап 5)

Реализованы **production entrypoint** с ожиданием PostgreSQL и автоматическим **`alembic upgrade head`**, усиленный **healthcheck** у `postgres`, том **`./backups`**, скрипты **`backup.sh` / `restore.sh`**, **Makefile** для типовых операций и обновлённая DevOps‑документация в этом README. Дальнейшие улучшения: секреты в Docker Swarm/Kubernetes, мониторинг, off-site бэкапы, CI для проверки миграций.
