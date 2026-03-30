"""
Точка входа процесса Telegram-бота: polling, middleware, роутеры.
"""

from __future__ import annotations

import asyncio
import logging

import worker.celery_app  # noqa: F401 — загрузить Celery и зарегистрировать tasks до импорта хендлеров

from aiogram import Bot, Dispatcher

from infrastructure.config import get_settings
from presentation.telegram.handlers.tender_handler import router as tender_router
from presentation.telegram.middlewares.media_group import MediaGroupMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Инициализация диспетчера и long polling (схема БД — через Alembic)."""
    settings = get_settings()

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()

    dp.message.middleware(MediaGroupMiddleware())
    dp.include_router(tender_router)

    # Иначе getUpdates падает с Conflict, если для токена ранее включали webhook.
    await bot.delete_webhook(drop_pending_updates=False)
    logger.info("Бот запущен (polling)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
