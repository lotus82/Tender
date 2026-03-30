"""Порт уведомлений: ядро не знает о Telegram и других каналах доставки."""

from abc import ABC, abstractmethod


class INotificationPort(ABC):
    """Абстракция отправки сообщений пользователю по произвольному каналу."""

    @abstractmethod
    async def send_message(self, user_id: str, text: str) -> None:
        """
        Отправить текстовое сообщение пользователю.

        :param user_id: Идентификатор пользователя в канале (например, chat_id в Telegram).
        :param text: Текст сообщения.
        """
