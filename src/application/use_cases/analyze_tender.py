"""
Сценарий анализа тендерной документации: только порты, без Telegram/Celery.

Оркестрация: сохранение заявки → загрузка файлов → парсинг → LLM → обновление статуса → уведомление.
"""

from __future__ import annotations

import logging

from application.ports.file_provider import IFileProviderPort
from application.ports.llm import ILLMPort
from application.ports.notification import INotificationPort
from application.ports.repository import ITenderRequestRepository
from application.services.parsers import parse_bytes_to_markdown
from domain.entities import TenderRequest, TenderRequestStatus, TenderUserInfo
from domain.exceptions import DocumentParsingError, FileDownloadError, LLMAnalysisError

logger = logging.getLogger(__name__)


class AnalyzeTenderUseCase:
    """Прикладной сценарий полного цикла: персистенция, файлы, LLM, ответ пользователю."""

    def __init__(
        self,
        file_provider: IFileProviderPort,
        llm: ILLMPort,
        notifier: INotificationPort,
        tender_requests: ITenderRequestRepository,
    ) -> None:
        self._files = file_provider
        self._llm = llm
        self._notify = notifier
        self._repo = tender_requests

    async def execute(
        self,
        user_id: int,
        query: str,
        file_ids: list[str],
        *,
        username: str | None = None,
        display_name: str | None = None,
    ) -> None:
        """
        Выполнить анализ: зафиксировать заявку в БД (PROCESSING), обработать файлы, обновить статус.

        При ошибках статус ``FAILED`` и ``result_text`` с причиной; пользователю уходит локализованное сообщение.
        """
        uid = str(user_id)
        user_info = TenderUserInfo(
            external_user_id=uid,
            display_name=display_name,
            username=username,
        )
        initial = TenderRequest(
            text_query=query,
            user=user_info,
            status=TenderRequestStatus.PROCESSING,
            documents=[],
        )
        saved = await self._repo.save(initial)
        rid = saved.id
        if rid is None:
            logger.error("Репозиторий не вернул id заявки после save")
            await self._notify.send_message(
                uid,
                "Не удалось сохранить заявку. Повторите попытку позже.",
            )
            return

        combined_parts: list[str] = []

        try:
            for idx, fid in enumerate(file_ids, start=1):
                raw = await self._files.download_file(fid)
                try:
                    md = parse_bytes_to_markdown(raw)
                except DocumentParsingError as exc:
                    logger.warning("Парсинг файла %s: %s", fid, exc)
                    await self._repo.update_status(
                        rid,
                        TenderRequestStatus.FAILED.value,
                        result_text=str(exc),
                    )
                    await self._notify.send_message(
                        uid,
                        f"Не удалось разобрать один из файлов (№{idx}). "
                        f"Проверьте формат (PDF, DOCX, XLSX или изображение). Подробности: {exc}",
                    )
                    return
                combined_parts.append(f"### Вложение {idx} (id: `{fid}`)\n\n{md}")

            documents_markdown = "\n\n".join(combined_parts)
            answer = await self._llm.analyze(query, documents_markdown)
            await self._repo.update_status(
                rid,
                TenderRequestStatus.COMPLETED.value,
                result_text=answer,
            )
            await self._notify.send_message(uid, answer)

        except FileDownloadError as exc:
            logger.warning("Загрузка файла: %s", exc)
            await self._repo.update_status(
                rid,
                TenderRequestStatus.FAILED.value,
                result_text=str(exc),
            )
            await self._notify.send_message(
                uid,
                "Не удалось загрузить файл из хранилища. Попробуйте отправить документы ещё раз.",
            )
        except LLMAnalysisError as exc:
            logger.warning("LLM: %s", exc)
            await self._repo.update_status(
                rid,
                TenderRequestStatus.FAILED.value,
                result_text=str(exc),
            )
            await self._notify.send_message(
                uid,
                f"Ошибка анализа моделью (таймаут или отказ сервиса). Повторите запрос позже. Детали: {exc}",
            )
        except Exception as exc:
            logger.exception("Неожиданная ошибка сценария анализа")
            await self._repo.update_status(
                rid,
                TenderRequestStatus.FAILED.value,
                result_text=str(exc),
            )
            await self._notify.send_message(
                uid,
                "Произошла внутренняя ошибка при обработке заявки. Обратитесь к администратору.",
            )
