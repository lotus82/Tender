"""Асинхронный движок SQLAlchemy и фабрика сессий (инфраструктура БД)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from infrastructure.config import get_settings
from infrastructure.db.base import Base


_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_async_engine() -> AsyncEngine:
    """Вернуть singleton async engine (создаётся при первом обращении)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
        )
    return _engine


def get_async_session_maker() -> async_sessionmaker[AsyncSession]:
    """Фабрика async-сессий, привязанная к текущему engine."""
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(
            get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_maker


async def dispose_async_engine() -> None:
    """
    Закрыть пул соединений и сбросить singleton.

    Обязательно вызывать после ``asyncio.run()`` в Celery: каждый запуск создаёт новый
    event loop, а старый AsyncEngine остаётся привязанным к уже закрытому loop —
    иначе MissingGreenlet / ошибки соединения (см. документацию SQLAlchemy asyncio).
    """
    global _engine, _session_maker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_maker = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Одна сессия с commit при успехе и rollback при ошибке."""
    factory = get_async_session_maker()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """
    Создать таблицы по metadata (только для быстрых локальных тестов).

    Для нормального контура используйте Alembic (см. README).
    """
    import infrastructure.db.models  # noqa: F401 — регистрация таблиц в Base.metadata

    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
