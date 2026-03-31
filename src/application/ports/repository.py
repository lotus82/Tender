"""Порт доступа к персистентным заявкам (без SQLAlchemy в прикладном слое)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.entities import TenderRequest


class ITenderRequestRepository(ABC):
    """Абстракция хранения заявок на анализ тендерной документации."""

    @abstractmethod
    async def save(self, request: TenderRequest) -> TenderRequest:
        """
        Сохранить новую заявку (и при необходимости пользователя).

        Возвращает сущность с заполненными ``id`` и ``created_at``.
        """

    @abstractmethod
    async def get_by_id(self, request_id: str | int) -> TenderRequest | None:
        """Найти заявку по первичному ключу; вложения в домене могут быть пустыми."""

    @abstractmethod
    async def update_status(
        self,
        request_id: str | int,
        status: str,
        result_text: str | None = None,
    ) -> None:
        """
        Обновить статус и опционально текст результата или причины ошибки.

        :param status: Строковое значение статуса (обычно ``TenderRequestStatus.value``).
        """

    @abstractmethod
    async def fail_latest_processing_for_user(
        self,
        telegram_user_id: int,
        result_text: str,
    ) -> bool:
        """
        Пометить последнюю заявку пользователя в статусе PROCESSING как FAILED.

        Нужна при прерывании Celery по soft time limit, когда id заявки недоступен снаружи сценария.
        Возвращает True, если такая строка найдена и обновлена.
        """
