"""
Middleware агрегации медиа-альбомов Telegram (media group).

Telegram рассылает альбом как несколько отдельных апдейтов с общим media_group_id.
Middleware накапливает сообщения группы и вызывает следующий обработчик один раз
после паузы (debounce), чтобы сформировать единый список вложений.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from domain.entities import TenderDocument

logger = logging.getLogger(__name__)

# Задержка после последнего сообщения альбома перед вызовом хендлера (секунды).
_MEDIA_GROUP_DEBOUNCE_SEC = 3.0


def _extract_documents_from_message(message: Message) -> list[TenderDocument]:
    """Собрать доменные описания вложений из одного сообщения (документ и/или фото)."""
    items: list[TenderDocument] = []

    if message.document is not None:
        doc = message.document
        name = doc.file_name or f"file_{doc.file_id}"
        mime = doc.mime_type or "application/octet-stream"
        items.append(
            TenderDocument(file_id=doc.file_id, file_name=name, mime_type=mime),
        )

    if message.photo:
        photo = message.photo[-1]
        items.append(
            TenderDocument(
                file_id=photo.file_id,
                file_name="photo.jpg",
                mime_type="image/jpeg",
            ),
        )

    return items


def _combined_query_text(batch: list[Message]) -> str:
    """Текст запроса: подпись или текст любого сообщения группы (обычно подпись на первом элементе)."""
    for msg in batch:
        if msg.caption is not None and msg.caption.strip():
            return msg.caption.strip()
    for msg in batch:
        if msg.text is not None and msg.text.strip():
            return msg.text.strip()
    return ""


class MediaGroupMiddleware(BaseMiddleware):
    """
    Перехватывает сообщения с media_group_id, буферизует их и вызывает цепочку один раз.

    Для сообщений без альбома сразу прокидывает в data списки ``tender_documents`` и
    ``user_query_text`` и вызывает handler.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._buffers: dict[str, list[Message]] = {}
        self._debounce_tasks: dict[str, asyncio.Task[None]] = {}
        self._latest_data: dict[str, dict[str, Any]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        message = event

        if message.media_group_id is None:
            documents = _extract_documents_from_message(message)
            query_text = (message.text or message.caption or "").strip()
            data["tender_documents"] = documents
            data["user_query_text"] = query_text
            return await handler(event, data)

        group_key = str(message.media_group_id)

        async def _flush_after_debounce() -> None:
            try:
                await asyncio.sleep(_MEDIA_GROUP_DEBOUNCE_SEC)
            except asyncio.CancelledError:
                # Отмена означает новое сообщение альбома — ждём следующий таймер.
                return

            async with self._lock:
                batch = self._buffers.pop(group_key, [])
                flush_data = self._latest_data.pop(group_key, {}).copy()
                self._debounce_tasks.pop(group_key, None)

            if not batch:
                return

            batch.sort(key=lambda m: m.message_id)
            merged_docs: list[TenderDocument] = []
            for msg in batch:
                merged_docs.extend(_extract_documents_from_message(msg))

            flush_data["tender_documents"] = merged_docs
            flush_data["user_query_text"] = _combined_query_text(batch)

            try:
                await handler(batch[0], flush_data)
            except Exception:
                logger.exception("Ошибка при обработке агрегированного альбома")
                raise

        async with self._lock:
            self._buffers.setdefault(group_key, []).append(message)
            self._latest_data[group_key] = data.copy()

            previous = self._debounce_tasks.get(group_key)
            if previous is not None and not previous.done():
                previous.cancel()

            task = asyncio.create_task(_flush_after_debounce())
            self._debounce_tasks[group_key] = task

        # Промежуточные сообщения альбома не передаём дальше по цепочке сразу.
        return None
