"""Абстрактные порты (интерфейсы) для инфраструктурных возможностей."""

from application.ports.file_provider import IFileProviderPort
from application.ports.llm import ILLMPort
from application.ports.notification import INotificationPort
from application.ports.repository import ITenderRequestRepository

__all__ = [
    "IFileProviderPort",
    "ILLMPort",
    "INotificationPort",
    "ITenderRequestRepository",
]
