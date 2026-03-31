"""Адаптер порта уведомлений: отправка сообщений через aiogram.Bot."""

from __future__ import annotations

import re

from aiogram import Bot
from aiogram.types import BufferedInputFile

from application.ports.notification import INotificationPort

# Telegram: до 4096 UTF-16 кодовых единиц на сообщение; режем чуть меньше с запасом.
_CHUNK_UTF16 = 4000

# Ответ LLM иногда содержит псевдо-HTML (<b>); без parse_mode это мусор, плюс риск для клиентов.
_HTML_LIKE_TAG = re.compile(r"<[^>]+>")


def _strip_llm_html_tags(text: str) -> str:
    """Убрать теги вида ``<b>`` / ``</p>``, оставив видимый текст."""
    return _HTML_LIKE_TAG.sub("", text)


def _utf16_length(s: str) -> int:
    n = 0
    for ch in s:
        n += 2 if ord(ch) > 0xFFFF else 1
    return n


def _split_for_telegram(text: str, max_utf16: int = _CHUNK_UTF16) -> list[str]:
    """Разбить строку на части, каждая ≤ max_utf16 в UTF-16."""
    if _utf16_length(text) <= max_utf16:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    cur = 0
    for ch in text:
        u = 2 if ord(ch) > 0xFFFF else 1
        if cur + u > max_utf16 and buf:
            chunks.append("".join(buf))
            buf = []
            cur = 0
        buf.append(ch)
        cur += u
    if buf:
        chunks.append("".join(buf))
    return chunks


class TelegramNotificationAdapter(INotificationPort):
    """
    Реализация INotificationPort для Telegram.

    Принимает экземпляр Bot; user_id — строковый chat_id получателя в ``send_message``,
    целочисленный chat_id в ``send_documents``.
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_message(self, user_id: str, text: str) -> None:
        """Отправить текст в чат; длинный текст режется по лимиту UTF-16 Telegram."""
        chat_id = int(user_id)
        cleaned = _strip_llm_html_tags(text)
        for chunk in _split_for_telegram(cleaned, _CHUNK_UTF16):
            await self._bot.send_message(chat_id=chat_id, text=chunk)

    async def send_documents(self, user_id: int, files: list[tuple[str, bytes]]) -> None:
        """Отправить документы по одному (обход лимитов медиа-групп)."""
        chat_id = user_id
        for filename, raw in files:
            if not raw:
                continue
            doc = BufferedInputFile(file=raw, filename=filename)
            await self._bot.send_document(chat_id=chat_id, document=doc)
