"""Адаптер порта файлов: загрузка по Telegram file_id через aiogram.Bot."""

from __future__ import annotations

import io
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from application.ports.file_provider import DownloadedFile, IFileProviderPort
from domain.exceptions import FileDownloadError

logger = logging.getLogger(__name__)


class TelegramFileProviderAdapter(IFileProviderPort):
    """Скачивание файлов с серверов Telegram Bot API."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def download_file(
        self,
        file_id: str,
        *,
        original_filename: str | None = None,
    ) -> DownloadedFile:
        """Получить байты файла по ``file_id`` и осмысленное имя файла."""
        try:
            tg_file = await self._bot.get_file(file_id)
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

        path_name = "file.bin"
        if tg_file.file_path:
            path_name = tg_file.file_path.split("/")[-1] or path_name

        name = (original_filename or "").strip()
        if not name:
            name = path_name

        return DownloadedFile(content=data, filename=name)
