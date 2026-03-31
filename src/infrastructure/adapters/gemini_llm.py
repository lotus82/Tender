"""Адаптер ILLMPort для Google Gemini (SDK google-genai)."""

from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types

from application.ports.llm import ILLMPort
from application.services.prompt_manager import PromptManager
from domain.exceptions import LLMAnalysisError
from infrastructure.config import get_settings

logger = logging.getLogger(__name__)


class GeminiAdapter(ILLMPort):
    """
    Вызов ``generate_content`` с системной инструкцией и шаблоном пользовательского промпта из ``PromptManager``.

    Тексты промптов читаются с диска при каждом запросе через менеджер (горячая подмена файлов).
    """

    def __init__(self, api_key: str, prompt_manager: PromptManager) -> None:
        settings = get_settings()
        self._prompt_manager = prompt_manager
        self._model = settings.gemini_model
        self._timeout_ms = settings.gemini_timeout_ms
        self._max_output_tokens = settings.gemini_max_output_tokens
        self._timeout_sec = max(self._timeout_ms / 1000.0, 1.0)
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=self._timeout_ms),
        )

    async def analyze(self, query: str, documents_text: str) -> str:
        system_instruction = self._prompt_manager.get_system_instruction()
        template = self._prompt_manager.get_tender_analysis_template()
        try:
            user_prompt = template.format(
                user_query=query.strip() or "(Запрос не указан — дай обзор документов.)",
                documents_text=documents_text.strip() or "(Документы пусты.)",
            )
        except KeyError as exc:
            raise LLMAnalysisError(
                f"Шаблон промпта содержит неизвестный плейсхолдер: {exc}",
            ) from exc

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
            max_output_tokens=self._max_output_tokens,
        )

        async def _call_model() -> types.GenerateContentResponse:
            return await self._client.aio.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=config,
            )

        try:
            response = await asyncio.wait_for(
                _call_model(),
                timeout=self._timeout_sec + 15.0,
            )
        except TimeoutError as exc:
            raise LLMAnalysisError("Превышено время ожидания ответа Gemini.") from exc
        except Exception as exc:
            logger.warning("Вызов Gemini завершился ошибкой: %s", exc)
            raise LLMAnalysisError(f"Сбой API Gemini: {exc}") from exc

        text = self._extract_text(response)
        self._log_finish_reason(response)
        if not text.strip():
            raise LLMAnalysisError("Модель вернула пустой ответ.")
        return text

    @staticmethod
    def _log_finish_reason(response: object) -> None:
        """Предупреждение в лог, если ответ обрезан по лимиту токенов."""
        try:
            candidates = getattr(response, "candidates", None) or []
            if not candidates:
                return
            c0 = candidates[0]
            fr = getattr(c0, "finish_reason", None)
            if fr is None:
                return
            fr_name = getattr(fr, "name", None) or str(fr)
            if "MAX_TOKENS" in fr_name.upper():
                logger.warning(
                    "Ответ Gemini обрезан по max_output_tokens (finish_reason=%s). "
                    "Увеличьте GEMINI_MAX_OUTPUT_TOKENS при необходимости.",
                    fr_name,
                )
        except Exception:
            pass

    @staticmethod
    def _extract_text(response: types.GenerateContentResponse) -> str:
        """Достать текст из ответа SDK (свойство ``text`` или ручной обход)."""
        raw = getattr(response, "text", None)
        if isinstance(raw, str) and raw.strip():
            return raw
        try:
            candidates = getattr(response, "candidates", None) or []
            if not candidates:
                return ""
            parts: list[str] = []
            content = getattr(candidates[0], "content", None)
            if content is None:
                return ""
            for part in getattr(content, "parts", None) or []:
                t = getattr(part, "text", None)
                if t:
                    parts.append(t)
            return "\n".join(parts)
        except Exception:
            return ""
