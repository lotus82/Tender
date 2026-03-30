"""Доменные сущности заявки на анализ тендера и вложенных документов."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class TenderRequestStatus(StrEnum):
    """Жизненный цикл обработки заявки (машина состояний персистентного слоя)."""

    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class TenderUserInfo:
    """Идентификация пользователя в канале доставки (без привязки к Telegram в именах полей)."""

    external_user_id: str
    display_name: str | None = None
    username: str | None = None


@dataclass(slots=True)
class TenderDocument:
    """Метаданные одного файла, переданного для анализа."""

    file_id: str
    file_name: str
    mime_type: str


@dataclass(slots=True)
class TenderRequest:
    """Заявка на разбор тендерной документации: запрос, статус, результат анализа."""

    text_query: str
    user: TenderUserInfo
    status: TenderRequestStatus = TenderRequestStatus.RECEIVED
    documents: list[TenderDocument] = field(default_factory=list)
    """Идентификатор строки в БД после сохранения (``RequestLog.id``)."""
    id: int | None = None
    created_at: datetime | None = None
    result_text: str | None = None
    external_request_id: str | None = None
