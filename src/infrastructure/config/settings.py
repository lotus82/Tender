"""Настройки приложения на базе Pydantic Settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Централизованная конфигурация из переменных окружения."""

    model_config = SettingsConfigDict(
        # Сначала пример из репозитория, затем локальный .env (перекрывает). Файлы могут отсутствовать.
        env_file=(".env.example", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(
        ...,
        description="Токен Telegram Bot API",
    )
    database_url: str = Field(
        ...,
        description="Async SQLAlchemy URL, например postgresql+asyncpg://user:pass@host:5432/db",
    )
    redis_url: str = Field(
        ...,
        description="URL Redis для брокера Celery и при необходимости кэша",
    )
    prompts_dir: Path = Field(
        default=Path("prompts"),
        description="Каталог с system_instruction.txt и tender_analysis_template.txt (горячая подмена без перезапуска)",
    )
    gemini_api_key: str = Field(
        ...,
        description="API-ключ Google Gemini (google-genai)",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description=(
            "Идентификатор модели Gemini для generateContent (стабильные: gemini-2.5-flash, "
            "gemini-2.5-pro; старые имена вроде gemini-1.5-pro в API могут отдавать 404)"
        ),
    )
    gemini_timeout_ms: int = Field(
        default=180_000,
        ge=1_000,
        description="Таймаут HTTP-запроса к Gemini API в миллисекундах",
    )
    gemini_max_output_tokens: int = Field(
        default=16_384,
        ge=512,
        le=65_536,
        description="Лимит токенов ответа Gemini; малые значения обрезают длинный разбор",
    )

    celery_broker_url: str | None = Field(
        default=None,
        description="Переопределение URL брокера Celery; по умолчанию совпадает с redis_url",
    )
    celery_result_backend: str | None = Field(
        default=None,
        description="Бэкенд результатов Celery; по умолчанию redis_url",
    )

    @property
    def celery_broker(self) -> str:
        """URL брокера для Celery."""
        return self.celery_broker_url or self.redis_url

    @property
    def celery_backend(self) -> str:
        """URL бэкенда результатов Celery."""
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    """Ленивая singleton-загрузка настроек (кэшируется на процесс)."""
    return Settings()
