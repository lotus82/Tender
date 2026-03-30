"""
Обработчик заявок на анализ тендерных документов (слой представления Telegram).

Не импортирует Celery и не содержит бизнес-оркестрации прикладного слоя — только
приём вложений, ответ пользователю и подготовка доменного объекта для будущей очереди.
"""

from __future__ import annotations

import logging
from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.types import Message

from domain.entities import TenderDocument, TenderRequest, TenderRequestStatus, TenderUserInfo
from worker.tasks import process_tender_task

logger = logging.getLogger(__name__)

router = Router(name="tender")


class HasTenderAttachmentFilter(BaseFilter):
    """Пропускать сообщения с документом, фото или принадлежащие медиа-группе."""

    async def __call__(self, message: Message) -> bool:
        return bool(
            message.document
            or message.photo
            or message.media_group_id is not None,
        )


@router.message(HasTenderAttachmentFilter())
async def handle_tender_submission(
    message: Message,
    tender_documents: list[TenderDocument],
    user_query_text: str,
) -> None:
    """
    Обработать агрегированные вложения и текст запроса.

    Поля ``tender_documents`` и ``user_query_text`` выставляет MediaGroupMiddleware.
    """
    documents = tender_documents

    if not documents:
        return

    if message.from_user is None:
        logger.warning("Сообщение без from_user, пропуск")
        return

    user_info = TenderUserInfo(
        external_user_id=str(message.from_user.id),
        display_name=message.from_user.full_name,
        username=message.from_user.username,
    )

    payload = TenderRequest(
        text_query=user_query_text,
        user=user_info,
        status=TenderRequestStatus.RECEIVED,
        documents=list(documents),
    )

    await message.answer(
        "Ваши документы получены и обрабатываются. Пожалуйста, дождитесь результата.",
    )

    file_ids = [doc.file_id for doc in documents]
    process_tender_task.delay(
        message.from_user.id,
        user_query_text,
        file_ids,
        username=message.from_user.username,
        display_name=message.from_user.full_name,
    )
    _ = payload  # доменный объект пригодится при расширении (аудит, БД)
