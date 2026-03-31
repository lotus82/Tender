"""
Сценарий анализа тендерной документации: только порты, без Telegram/Celery.

Оркестрация: сохранение заявки → загрузка файлов → парсинг → LLM → артефакты → уведомление.
"""

from __future__ import annotations

import logging
from pathlib import Path

from application.ports.file_provider import IFileProviderPort
from application.ports.llm import ILLMPort
from application.ports.notification import INotificationPort
from application.ports.repository import ITenderRequestRepository
from application.services.parsers import parse_bytes_to_markdown
from application.services.pdf_generator import markdown_response_to_pdf
from domain.entities import TenderRequest, TenderRequestStatus, TenderUserInfo
from domain.exceptions import DocumentParsingError, FileDownloadError, LLMAnalysisError

logger = logging.getLogger(__name__)


def _parsed_txt_filename(original_filename: str) -> str:
    """Имя артефакта: ``parsed_<оригинал>.txt`` (только базовое имя, без путей)."""
    base = Path(original_filename).name.strip() or "document"
    return f"parsed_{base}.txt"


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
        file_entries: list[tuple[str, str]],
        *,
        username: str | None = None,
        display_name: str | None = None,
    ) -> None:
        """
        Выполнить анализ: зафиксировать заявку в БД (PROCESSING), обработать файлы, обновить статус.

        ``file_entries`` — пары ``(file_id, original_filename)`` из канала доставки.

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
        txt_artifacts: list[tuple[str, bytes]] = []

        try:
            for idx, (fid, orig_name) in enumerate(file_entries, start=1):
                downloaded = await self._files.download_file(
                    fid,
                    original_filename=orig_name,
                )
                raw = downloaded.content
                display_name = downloaded.filename
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
                combined_parts.append(
                    f"### Вложение {idx} ({display_name}, id: `{fid}`)\n\n{md}",
                )
                txt_name = _parsed_txt_filename(display_name)
                txt_artifacts.append((txt_name, md.encode("utf-8")))

            documents_markdown = "\n\n".join(combined_parts)
            answer = await self._llm.analyze(query, documents_markdown)
            await self._repo.update_status(
                rid,
                TenderRequestStatus.COMPLETED.value,
                result_text=answer,
            )
            await self._notify.send_message(uid, answer)

            files_to_send: list[tuple[str, bytes]] = list(txt_artifacts)
            try:
                pdf_buf = markdown_response_to_pdf(answer)
                files_to_send.append(("Результаты анализа.pdf", pdf_buf.getvalue()))
            except Exception as exc:
                logger.warning("PDF результата анализа не сформирован: %s", exc)

            if files_to_send:
                await self._notify.send_documents(user_id, files_to_send)

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
