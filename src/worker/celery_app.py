"""
Приложение Celery: брокер и бэкенд из Pydantic Settings (Redis).

Задачи подключаются через autodiscover пакета ``worker`` (модуль ``tasks``),
чтобы избежать циклических импортов с декоратором ``@app.task``.
"""

from __future__ import annotations

from celery import Celery

from infrastructure.config import get_settings

_settings = get_settings()

app = Celery(
    "tender_agent",
    broker=_settings.celery_broker,
    backend=_settings.celery_backend,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

app.autodiscover_tasks(packages=["worker"], related_name="tasks", force=True)
