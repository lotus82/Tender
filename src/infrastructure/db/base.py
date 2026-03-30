"""Декларативная база для ORM-моделей инфраструктуры."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс таблиц SQLAlchemy (только инфраструктурный слой)."""

    pass
