"""Настройки приложения на базе Pydantic Settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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
        description="API-ключ Google Gemini (REST generateContent)",
    )
    gemini_model: str = Field(
        default="gemini-3.1-flash-lite-preview",
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
    gemini_base_url: str | None = Field(
        default=None,
        description=(
            "Необязательный базовый URL Gemini API (HTTP-прокси, например Cloudflare Worker). "
            "Пусто — запросы идут на стандартные endpoint’ы Google."
        ),
    )
    welcome_message: str = Field(
        default=(
            "Добро пожаловать! Отправьте мне текстовый запрос и прикрепите документы "
            "(до 10 файлов: PDF, DOCX, XLSX, JPG) в одном сообщении. "
            "Я проанализирую их на соответствие 44-ФЗ и 223-ФЗ."
        ),
        description="Текст ответа бота на команду /start",
    )
    llm_temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description="Температура генерации Gemini (REST generationConfig.temperature)",
    )
    processing_timeout_seconds: int = Field(
        default=180,
        ge=30,
        le=3_600,
        description="Мягкий лимит Celery (сек.): после него задача прерывается и пользователю уходит сообщение о таймауте",
    )

    celery_broker_url: str | None = Field(
        default=None,
        description="Переопределение URL брокера Celery; по умолчанию совпадает с redis_url",
    )
    celery_result_backend: str | None = Field(
        default=None,
        description="Бэкенд результатов Celery; по умолчанию redis_url",
    )

    @field_validator("gemini_base_url", mode="before")
    @classmethod
    def _empty_gemini_base_url_none(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s or None
        return None

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
