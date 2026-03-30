"""
ORM-модели пользователей и журнала заявок.

Доступ к данным — через репозиторий ``PostgresTenderRequestRepository`` (порт ``ITenderRequestRepository``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.db.base import Base


class User(Base):
    """Пользователь канала (например, Telegram), синхронизируемый с БД."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger(), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    request_logs: Mapped[list["RequestLog"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class RequestLog(Base):
    """Запись о заявке на анализ (статус, запрос, итог LLM или текст ошибки)."""

    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True, server_default="received")
    query_text: Mapped[str] = mapped_column(Text(), default="")
    result_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="request_logs")
