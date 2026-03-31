"""
Celery-задачи: на границе инфраструктуры собираются адаптеры и вызывается сценарий приложения.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.services.prompt_manager import PromptManager
from application.use_cases.analyze_tender import AnalyzeTenderUseCase
from infrastructure.adapters.gemini_llm import GeminiAdapter
from infrastructure.adapters.postgres_repository import PostgresTenderRequestRepository
from infrastructure.adapters.telegram_file_provider import TelegramFileProviderAdapter
from infrastructure.adapters.telegram_notifier import TelegramNotificationAdapter
from infrastructure.config import get_settings
from infrastructure.db.database import dispose_async_engine, get_async_session_maker
from worker.celery_app import app

logger = get_task_logger(__name__)


def _normalize_file_entries(file_entries: list[list[str]]) -> list[tuple[str, str]]:
    """Celery JSON даёт списки пар ``[file_id, file_name]``."""
    out: list[tuple[str, str]] = []
    for row in file_entries:
        if len(row) < 2:
            continue
        out.append((str(row[0]), str(row[1])))
    return out


async def _run_analyze(
    user_id: int,
    query: str,
    file_entries: list[list[str]],
    *,
    username: str | None,
    display_name: str | None,
) -> None:
    """Создать сессию БД, Bot, адаптеры и выполнить ``AnalyzeTenderUseCase``."""
    settings = get_settings()
    factory: async_sessionmaker[AsyncSession] = get_async_session_maker()

    try:
        async with factory() as session:
            try:
                repo = PostgresTenderRequestRepository(session)
                async with Bot(token=settings.telegram_bot_token) as bot:
                    file_provider = TelegramFileProviderAdapter(bot)
                    prompt_manager = PromptManager(settings.prompts_dir)
                    llm = GeminiAdapter(
                        api_key=settings.gemini_api_key,
                        prompt_manager=prompt_manager,
                    )
                    notifier = TelegramNotificationAdapter(bot)
                    use_case = AnalyzeTenderUseCase(file_provider, llm, notifier, repo)
                    await use_case.execute(
                        user_id=user_id,
                        query=query,
                        file_entries=_normalize_file_entries(file_entries),
                        username=username,
                        display_name=display_name,
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        await dispose_async_engine()


@app.task(name="tender.process_tender", bind=False)
def process_tender_task(
    user_id: int,
    query: str,
    file_entries: list[list[str]],
    username: str | None = None,
    display_name: str | None = None,
) -> None:
    """
    Фоновая обработка заявки: скачивание вложений, парсинг, LLM, ответ в чат, запись статуса в БД.

    ``file_entries`` — JSON-сериализуемый список пар ``[telegram_file_id, исходное_имя_файла]``.

    Celery вызывает синхронную функцию — асинхронный сценарий запускается через ``asyncio.run``.
    """
    logger.info("Старт process_tender_task user_id=%s файлов=%s", user_id, len(file_entries))
    try:
        asyncio.run(
            _run_analyze(
                user_id,
                query,
                file_entries,
                username=username,
                display_name=display_name,
            ),
        )
    except Exception:
        logger.exception("Ошибка в process_tender_task")
        raise
