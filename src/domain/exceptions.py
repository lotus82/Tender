"""Базовые доменные исключения. Обрабатываются на границах приложения (воркер, адаптеры)."""


class DomainError(Exception):
    """Базовая ошибка домена."""

    pass


class TenderAgentError(DomainError):
    """Общая ошибка агента тендерного анализа."""

    pass


class FileDownloadError(TenderAgentError):
    """Не удалось загрузить файл по внешнему идентификатору."""

    pass


class DocumentParsingError(TenderAgentError):
    """Ошибка разбора документа в текст/Markdown."""

    pass


class LLMAnalysisError(TenderAgentError):
    """Ошибка вызова LLM (таймаут, отказ API, пустой ответ)."""

    pass


# Обратная совместимость со старым именем
LlmAnalysisError = LLMAnalysisError
