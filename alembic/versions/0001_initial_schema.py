"""Начальная схема: users и request_logs (с result_text).

Revision ID: 0001
Revises:
Create Date: 2026-03-30

Новые ревизии (после изменения моделей в ``infrastructure/db/models.py``) создавайте так::

    # На хосте (Windows), из корня репозитория:
    set PYTHONPATH=src
    set DATABASE_URL=postgresql+asyncpg://tender:tender@localhost:5432/tender
    alembic revision --autogenerate -m "краткое описание изменений"
    alembic upgrade head

В Docker см. раздел про миграции в README.md.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id"),
    )

    op.create_table(
        "request_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=64),
            server_default="received",
            nullable=False,
        ),
        sa.Column("query_text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_request_logs_user_id", "request_logs", ["user_id"], unique=False)
    op.create_index("ix_request_logs_status", "request_logs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_request_logs_status", table_name="request_logs")
    op.drop_index("ix_request_logs_user_id", table_name="request_logs")
    op.drop_table("request_logs")
    op.drop_table("users")
