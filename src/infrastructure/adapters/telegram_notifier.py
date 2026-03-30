"""Адаптер порта уведомлений: отправка сообщений через aiogram.Bot."""

from __future__ import annotations

from aiogram import Bot

from application.ports.notification import INotificationPort

# Лимит Telegram на длину одного сообщения; запас по символам.
_TELEGRAM_MAX_MESSAGE_LEN = 4096
_SAFE_CHUNK = 4000


class TelegramNotificationAdapter(INotificationPort):
    """
    Реализация INotificationPort для Telegram.

    Принимает экземпляр Bot; user_id — строковый chat_id получателя.
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_message(self, user_id: str, text: str) -> None:
        """Отправить текст в чат пользователя; длинный текст режется на несколько сообщений."""
        chat_id = int(user_id)
        if len(text) <= _TELEGRAM_MAX_MESSAGE_LEN:
            await self._bot.send_message(chat_id=chat_id, text=text)
            return
        for i in range(0, len(text), _SAFE_CHUNK):
            chunk = text[i : i + _SAFE_CHUNK]
            await self._bot.send_message(chat_id=chat_id, text=chunk)
