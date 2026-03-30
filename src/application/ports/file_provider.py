"""Порт доступа к файлам: загрузка по внешнему идентификатору без привязки к мессенджеру."""

from abc import ABC, abstractmethod


class IFileProviderPort(ABC):
    """Абстракция получения бинарного содержимого файла по идентификатору из внешней системы."""

    @abstractmethod
    async def download_file(self, file_id: str) -> bytes:
        """
        Загрузить файл по идентификатору во внешнем хранилище.

        :param file_id: Внешний идентификатор файла (например, Telegram file_id).
        :return: Сырые байты файла.
        """
