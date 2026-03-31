"""Адаптер ILLMPort для Google Gemini (REST v1beta через aiohttp)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from application.ports.llm import ILLMPort
from application.services.prompt_manager import PromptManager
from domain.exceptions import LLMAnalysisError
from infrastructure.config import get_settings

logger = logging.getLogger(__name__)


class GeminiAdapter(ILLMPort):
    """
    Вызов ``generateContent`` по REST API с системной инструкцией и пользовательским промптом из ``PromptManager``.

    Тексты промптов читаются с диска при каждом запросе через менеджер (горячая подмена файлов).
    """

    def __init__(
        self,
        api_key: str,
        prompt_manager: PromptManager,
        base_url: str | None = None,
    ) -> None:
        settings = get_settings()
        self._prompt_manager = prompt_manager
        self._model = settings.gemini_model
        self._max_output_tokens = settings.gemini_max_output_tokens
        self._llm_temperature = settings.llm_temperature
        self._timeout_sec = max(settings.gemini_timeout_ms / 1000.0, 1.0)
        self._api_key = api_key
        self.base_url = (base_url or "https://generativelanguage.googleapis.com").rstrip("/")

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

        endpoint = f"{self.base_url}/v1beta/models/{self._model}:generateContent"
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                },
            ],
            "generationConfig": {
                "temperature": self._llm_temperature,
                "maxOutputTokens": self._max_output_tokens,
            },
        }

        timeout = aiohttp.ClientTimeout(total=self._timeout_sec + 15.0)
        params = {"key": self._api_key}

        async def _post() -> dict[str, Any]:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    endpoint,
                    params=params,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    body_text = await response.text()
                    if response.status != 200:
                        raise LLMAnalysisError(
                            f"Gemini API HTTP {response.status}: {body_text}",
                        )
                    try:
                        return json.loads(body_text)
                    except json.JSONDecodeError as exc:
                        raise LLMAnalysisError(
                            f"Некорректный JSON от Gemini: {body_text[:500]}",
                        ) from exc

        try:
            data = await asyncio.wait_for(_post(), timeout=self._timeout_sec + 20.0)
        except TimeoutError as exc:
            raise LLMAnalysisError("Превышено время ожидания ответа Gemini.") from exc
        except aiohttp.ClientError as exc:
            logger.warning("HTTP-клиент Gemini: %s", exc)
            raise LLMAnalysisError(f"Сбой сети при вызове Gemini: {exc}") from exc
        except LLMAnalysisError:
            raise
        except Exception as exc:
            logger.warning("Вызов Gemini завершился ошибкой: %s", exc)
            raise LLMAnalysisError(f"Сбой API Gemini: {exc}") from exc

        text = self._extract_text_from_response(data)
        self._log_finish_reason(data)
        if not text.strip():
            raise LLMAnalysisError("Модель вернула пустой ответ.")
        return text

    @staticmethod
    def _log_finish_reason(data: dict[str, Any]) -> None:
        try:
            candidates = data.get("candidates") or []
            if not candidates:
                return
            c0 = candidates[0]
            if not isinstance(c0, dict):
                return
            fr = c0.get("finishReason")
            if fr is None:
                return
            fr_name = str(fr)
            if "MAX_TOKENS" in fr_name.upper():
                logger.warning(
                    "Ответ Gemini обрезан по max_output_tokens (finishReason=%s). "
                    "Увеличьте GEMINI_MAX_OUTPUT_TOKENS при необходимости.",
                    fr_name,
                )
        except Exception:
            pass

    @staticmethod
    def _extract_text_from_response(data: dict[str, Any]) -> str:
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        c0 = candidates[0]
        if not isinstance(c0, dict):
            return ""
        content = c0.get("content") or {}
        if not isinstance(content, dict):
            return ""
        parts = content.get("parts") or []
        texts: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                t = part.get("text")
                if isinstance(t, str) and t:
                    texts.append(t)
        return "\n".join(texts)
