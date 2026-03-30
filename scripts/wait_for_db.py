"""
Ожидание готовности PostgreSQL по DATABASE_URL (asyncpg).

Используется entrypoint контейнера приложения до запуска Alembic.
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

# Максимум попыток и пауза между ними (секунды).
_MAX_ATTEMPTS = 60
_SLEEP_SEC = 2


def _sync_dsn() -> str:
    """Преобразовать async DSN в форму, понятную asyncpg.connect."""
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        print("[wait_for_db] Ошибка: переменная DATABASE_URL не задана.", file=sys.stderr)
        sys.exit(1)
    return raw.replace("postgresql+asyncpg://", "postgresql://")


async def _wait() -> None:
    dsn = _sync_dsn()
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            conn = await asyncio.wait_for(asyncpg.connect(dsn=dsn), timeout=5)
            await conn.close()
            print("[wait_for_db] PostgreSQL принимает подключения.")
            return
        except Exception as exc:
            print(
                f"[wait_for_db] Попытка {attempt}/{_MAX_ATTEMPTS}: ожидание БД… ({exc!r})",
                flush=True,
            )
            await asyncio.sleep(_SLEEP_SEC)
    print("[wait_for_db] Превышено время ожидания PostgreSQL.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    asyncio.run(_wait())


if __name__ == "__main__":
    main()
