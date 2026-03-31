"""Порт доступа к файлам: загрузка по внешнему идентификатору без привязки к мессенджеру."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DownloadedFile:
    """Результат загрузки: сырые байты и имя файла для отображения/артефактов."""

    content: bytes
    filename: str


class IFileProviderPort(ABC):
    """Абстракция получения бинарного содержимого файла по идентификатору из внешней системы."""

    @abstractmethod
    async def download_file(
        self,
        file_id: str,
        *,
        original_filename: str | None = None,
    ) -> DownloadedFile:
        """
        Загрузить файл по идентификатору во внешнем хранилище.

        :param file_id: Внешний идентификатор файла (например, Telegram file_id).
        :param original_filename: Имя из метаданных канала; если нет — провайдер подставляет запасной вариант.
        :return: Байты и имя файла.
        """
