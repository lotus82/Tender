"""Абстрактные порты (интерфейсы) для инфраструктурных возможностей."""

from application.ports.file_provider import DownloadedFile, IFileProviderPort
from application.ports.llm import ILLMPort
from application.ports.notification import INotificationPort
from application.ports.repository import ITenderRequestRepository

__all__ = [
    "DownloadedFile",
    "IFileProviderPort",
    "ILLMPort",
    "INotificationPort",
    "ITenderRequestRepository",
]
