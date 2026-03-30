FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Шаблон переменных для Pydantic (env_file); переменные из docker-compose имеют приоритет выше файла.
COPY .env.example /app/.env.example

COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic

COPY prompts /app/prompts

COPY src /app/src

COPY scripts/entrypoint.sh /app/scripts/entrypoint.sh
COPY scripts/wait_for_db.py /app/scripts/wait_for_db.py
RUN chmod +x /app/scripts/entrypoint.sh /app/scripts/wait_for_db.py

# Точка входа: ожидание БД, миграции, затем CMD из compose (бот или worker)
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
