"""Адаптер порта файлов: загрузка по Telegram file_id через aiogram.Bot."""

from __future__ import annotations

import io
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from application.ports.file_provider import IFileProviderPort
from domain.exceptions import FileDownloadError

logger = logging.getLogger(__name__)


class TelegramFileProviderAdapter(IFileProviderPort):
    """Скачивание файлов с серверов Telegram Bot API."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def download_file(self, file_id: str) -> bytes:
        """Получить байты файла по ``file_id``."""
        try:
            buf = io.BytesIO()
            await self._bot.download(file=file_id, destination=buf, timeout=120)
            buf.seek(0)
            data = buf.read()
        except TelegramAPIError as exc:
            logger.warning("Telegram API при загрузке файла: %s", exc)
            raise FileDownloadError(str(exc)) from exc
        except Exception as exc:
            logger.exception("Сбой загрузки файла из Telegram")
            raise FileDownloadError(str(exc)) from exc

        if not data:
            raise FileDownloadError("Получен пустой файл.")
        return data
