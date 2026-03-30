"""
Загрузка текстов промптов с диска при каждом обращении (без кэша в памяти процесса).

Используется адаптером LLM; каталог задаётся из настроек (например volume в Docker).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_FALLBACK_SYSTEM = (
    "Ты — эксперт по закупкам 44-ФЗ и 223-ФЗ в РФ. Отвечай по-русски, без приветствий, "
    "в строгом Markdown. Если текст документов бессвязный — напиши: "
    "'Предоставленные документы не содержат релевантной информации'."
)
_FALLBACK_TEMPLATE = (
    "Выполни задачу на основе материалов.\n\n"
    "<user_query>\n{user_query}\n</user_query>\n\n"
    "<documents>\n{documents_text}\n</documents>\n\n"
    "Ответ структурируй по-русски в Markdown."
)


class PromptManager:
    """Читает ``system_instruction.txt`` и ``tender_analysis_template.txt`` при каждом вызове."""

    def __init__(self, prompts_dir: Path) -> None:
        self._dir = prompts_dir

    def _read_utf8(self, filename: str, *, fallback: str) -> str:
        path = self._dir / filename
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("Файл промпта не найден: %s — используется запасной текст.", path)
            return fallback
        except OSError as exc:
            logger.warning("Не удалось прочитать %s: %s — используется запасной текст.", path, exc)
            return fallback

    def get_system_instruction(self) -> str:
        """Содержимое ``system_instruction.txt`` (чтение с диска на каждый вызов)."""
        text = self._read_utf8("system_instruction.txt", fallback=_FALLBACK_SYSTEM).strip()
        return text if text else _FALLBACK_SYSTEM

    def get_tender_analysis_template(self) -> str:
        """Сырой шаблон ``tender_analysis_template.txt`` с плейсхолдерами ``{user_query}``, ``{documents_text}``."""
        text = self._read_utf8("tender_analysis_template.txt", fallback=_FALLBACK_TEMPLATE).strip()
        return text if text else _FALLBACK_TEMPLATE
