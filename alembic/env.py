"""
Окружение Alembic: асинхронный SQLAlchemy + метаданные моделей из ``src``.

Перед запуском задайте ``DATABASE_URL`` (например ``postgresql+asyncpg://...``).
Для автогенерации: ``alembic revision --autogenerate -m "описание"`` из корня проекта
с ``PYTHONPATH=src`` (или из контейнера — см. README).
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Корень репозитория и каталог ``src`` для импорта ``infrastructure.*``
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from infrastructure.db.base import Base  # noqa: E402
from infrastructure.db import models  # noqa: E402, F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """URL из переменной окружения или ``alembic.ini``."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    ini_url = config.get_main_option("sqlalchemy.url")
    if not ini_url or ini_url.startswith("driver://"):
        msg = "Задайте DATABASE_URL или sqlalchemy.url в alembic.ini"
        raise RuntimeError(msg)
    return ini_url


def run_migrations_offline() -> None:
    """Режим offline: только SQL в stdout (без подключения к БД)."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Синхронная часть миграций (вызывается из async-коннекта)."""
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Online-миграции через async engine (asyncpg)."""
    url = get_database_url()
    connectable = create_async_engine(url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Точка входа online-режима."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
