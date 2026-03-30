"""Порт вызова языковой модели без привязки к конкретному провайдеру."""

from abc import ABC, abstractmethod


class ILLMPort(ABC):
    """Абстракция анализа: запрос пользователя и текст документов передаются отдельно."""

    @abstractmethod
    async def analyze(self, query: str, documents_text: str) -> str:
        """
        Выполнить запрос к модели и вернуть сгенерированный текст.

        :param query: Формулировка задачи пользователя.
        :param documents_text: Сконкатенированный текст/Markdown документов.
        :return: Текст ответа модели.
        """
