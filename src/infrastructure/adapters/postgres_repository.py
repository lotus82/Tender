"""
Реализация репозитория заявок на PostgreSQL (SQLAlchemy async).

Соответствие домена: ``TenderRequest`` ↔ таблица ``request_logs`` + ``users``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from application.ports.repository import ITenderRequestRepository
from domain.entities import TenderRequest, TenderRequestStatus, TenderUserInfo
from infrastructure.db.models import RequestLog, User


class PostgresTenderRequestRepository(ITenderRequestRepository):
    """Персистенция заявок через ``AsyncSession`` (одна сессия на единицу работы)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_or_create_user(self, info: TenderUserInfo) -> User:
        """Найти или создать пользователя по ``external_user_id`` (Telegram id)."""
        tg_id = int(info.external_user_id)
        stmt = select(User).where(User.telegram_user_id == tg_id)
        user = await self._session.scalar(stmt)
        if user is not None:
            if info.username is not None:
                user.username = info.username
            if info.display_name:
                user.first_name = info.display_name[:255]
            return user

        user = User(
            telegram_user_id=tg_id,
            username=info.username,
            first_name=(info.display_name[:255] if info.display_name else None),
            last_name=None,
        )
        self._session.add(user)
        try:
            await self._session.flush()
        except IntegrityError:
            # Параллельные воркеры: оба прошли SELECT без строки и вставили одного пользователя.
            await self._session.rollback()
            existing = await self._session.scalar(
                select(User).where(User.telegram_user_id == tg_id),
            )
            if existing is None:
                raise
            if info.username is not None:
                existing.username = info.username
            if info.display_name:
                existing.first_name = info.display_name[:255]
            return existing
        return user

    @staticmethod
    def _row_to_domain(row: RequestLog, documents: list | None = None) -> TenderRequest:
        """Собрать доменную модель из ORM-строки."""
        u = row.user
        tg = str(u.telegram_user_id)
        user_info = TenderUserInfo(
            external_user_id=tg,
            display_name=u.first_name,
            username=u.username,
        )
        try:
            st = TenderRequestStatus(row.status)
        except ValueError:
            st = TenderRequestStatus.RECEIVED
        return TenderRequest(
            id=row.id,
            text_query=row.query_text or "",
            user=user_info,
            status=st,
            documents=list(documents or []),
            created_at=row.created_at,
            result_text=row.result_text,
        )

    async def save(self, request: TenderRequest) -> TenderRequest:
        """Вставить ``request_logs`` и вернуть сущность с ``id``/``created_at``."""
        if request.id is not None:
            msg = "Повторное сохранение с уже заданным id не поддерживается; используйте update_status."
            raise ValueError(msg)

        user = await self._get_or_create_user(request.user)
        row = RequestLog(
            user_id=user.id,
            status=request.status.value,
            query_text=request.text_query,
            result_text=request.result_text,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)

        created = row.created_at
        if created is None:
            created = datetime.now(timezone.utc)

        return TenderRequest(
            id=row.id,
            text_query=row.query_text,
            user=request.user,
            status=request.status,
            documents=list(request.documents),
            created_at=created,
            result_text=row.result_text,
        )

    async def get_by_id(self, request_id: str | int) -> TenderRequest | None:
        """Загрузить заявку с пользователем (eager ``user``)."""
        rid = int(request_id)
        stmt = (
            select(RequestLog)
            .where(RequestLog.id == rid)
            .options(selectinload(RequestLog.user))
        )
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        return self._row_to_domain(row, documents=[])

    async def update_status(
        self,
        request_id: str | int,
        status: str,
        result_text: str | None = None,
    ) -> None:
        """Обновить статус и при необходимости ``result_text``."""
        rid = int(request_id)
        values: dict[str, object] = {"status": status}
        if result_text is not None:
            values["result_text"] = result_text
        stmt = update(RequestLog).where(RequestLog.id == rid).values(**values)
        await self._session.execute(stmt)
        await self._session.flush()
