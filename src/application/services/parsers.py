"""
Парсинг бинарных документов в единый текстовый поток с таблицами в Markdown.

Используется фабрика по типу файла (сигнатура байтов и/или расширение ZIP для Office Open XML).
Таблицы приводятся к формату GitHub-таблиц: заголовок, разделитель |---|---|, строки данных.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Iterator
from typing import Any

import pandas as pd
import pdfplumber
import pytesseract
from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image

from domain.exceptions import DocumentParsingError


def _normalize_cell(value: Any) -> str:
    """Привести ячейку к однострочной строке без конфликтующих символов Markdown-таблицы."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = " ".join(text.splitlines())
    return text.replace("|", "¦").strip()


def table_rows_to_markdown(rows: list[list[Any]]) -> str:
    """
    Построить Markdown-таблицу из прямоугольной сетки ячеек.

    Первая строка считается заголовком; добавляется строка-разделитель ``|---|---|``.
    """
    if not rows:
        return ""
    normalized: list[list[str]] = []
    max_cols = max(len(r) for r in rows)
    for raw in rows:
        cells = [_normalize_cell(c) for c in raw]
        if len(cells) < max_cols:
            cells.extend([""] * (max_cols - len(cells)))
        normalized.append(cells[:max_cols])

    header = normalized[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for body_row in normalized[1:]:
        lines.append("| " + " | ".join(body_row) + " |")
    return "\n".join(lines)


def _iter_docx_block_items(document: DocxDocument) -> Iterator[Paragraph | Table]:
    """Обойти тело DOCX в порядке следования абзацев и таблиц."""
    for child in document.element.body:
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _docx_table_to_markdown(table: Table) -> str:
    """Преобразовать таблицу python-docx в Markdown."""
    rows: list[list[Any]] = []
    for row in table.rows:
        rows.append([cell.text for cell in row.cells])
    return table_rows_to_markdown(rows)


def parse_pdf_to_markdown(content: bytes) -> str:
    """
    Извлечь текст и таблицы из PDF через pdfplumber.

    Таблицы на каждой странице конвертируются в Markdown и вставляются после основного текста страницы.
    """
    parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                page_chunks: list[str] = []
                raw_text = page.extract_text()
                if raw_text and raw_text.strip():
                    page_chunks.append(raw_text.strip())

                tables = page.extract_tables() or []
                for ti, table in enumerate(tables, start=1):
                    if not table:
                        continue
                    md = table_rows_to_markdown(table)
                    if md:
                        page_chunks.append(f"### Таблица {ti} (стр. {i})\n\n{md}")

                if page_chunks:
                    parts.append(f"## Страница {i}\n\n" + "\n\n".join(page_chunks))
    except Exception as exc:
        raise DocumentParsingError(f"Не удалось разобрать PDF: {exc}") from exc

    if not parts:
        raise DocumentParsingError("PDF не содержит извлекаемого текста и таблиц.")
    return "\n\n".join(parts)


def parse_docx_to_markdown(content: bytes) -> str:
    """
    Обойти элементы DOCX: абзацы как текст, таблицы — в строгий Markdown.

    Порядок соответствует порядку блоков в документе.
    """
    try:
        document = Document(io.BytesIO(content))
    except Exception as exc:
        raise DocumentParsingError(f"Не удалось открыть DOCX: {exc}") from exc

    segments: list[str] = []
    for block in _iter_docx_block_items(document):
        if isinstance(block, Paragraph):
            t = block.text.strip()
            if t:
                segments.append(t)
        elif isinstance(block, Table):
            md = _docx_table_to_markdown(block)
            if md:
                segments.append(md)

    if not segments:
        raise DocumentParsingError("DOCX не содержит текста и таблиц.")
    return "\n\n".join(segments)


def parse_xlsx_to_markdown(content: bytes) -> str:
    """
    Прочитать все листы XLSX через pandas; каждый лист — Markdown-таблица (df.to_markdown).

    Требуется пакет ``tabulate`` для ``to_markdown``.
    """
    try:
        excel = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
    except Exception as exc:
        raise DocumentParsingError(f"Не удалось открыть XLSX: {exc}") from exc

    parts: list[str] = []
    for sheet in excel.sheet_names:
        try:
            df = pd.read_excel(excel, sheet_name=sheet)
            md = df.to_markdown(index=False)
            parts.append(f"## Лист «{sheet}»\n\n{md}")
        except Exception as exc:
            raise DocumentParsingError(f"Ошибка чтения листа «{sheet}»: {exc}") from exc

    if not parts:
        raise DocumentParsingError("XLSX не содержит листов с данными.")
    return "\n\n".join(parts)


def parse_image_to_text(content: bytes) -> str:
    """
    Распознать текст на изображении (скан, фото документа) через Tesseract.

    Языки: русский и английский (rus+eng).
    """
    try:
        image = Image.open(io.BytesIO(content))
    except Exception as exc:
        raise DocumentParsingError(f"Файл не является поддерживаемым изображением: {exc}") from exc

    try:
        text = pytesseract.image_to_string(image, lang="rus+eng")
    except Exception as exc:
        raise DocumentParsingError(f"Ошибка OCR: {exc}") from exc

    stripped = text.strip()
    if not stripped:
        raise DocumentParsingError("OCR не вернул текста (пустое изображение или нет текста).")
    return stripped


def detect_document_kind(data: bytes) -> str:
    """
    Грубая классификация по сигнатурам (без внешних зависимостей от имени файла).

    Возвращает: pdf, docx, xlsx, jpeg, png, unknown.
    """
    if len(data) >= 5 and data[:5] == b"%PDF-":
        return "pdf"
    if len(data) >= 2 and data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
        except zipfile.BadZipFile:
            return "unknown"
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        return "unknown"
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return "unknown"


ParserFn = Callable[[bytes], str]

_PARSERS: dict[str, ParserFn] = {
    "pdf": parse_pdf_to_markdown,
    "docx": parse_docx_to_markdown,
    "xlsx": parse_xlsx_to_markdown,
    "jpeg": parse_image_to_text,
    "png": parse_image_to_text,
}


def parse_bytes_to_markdown(content: bytes) -> str:
    """
    Выбрать парсер по типу содержимого и вернуть объединённый текст/Markdown.

    Для ``unknown`` сначала пробуем изображение (на случай нестандартных MIME).
    """
    kind = detect_document_kind(content)
    if kind in _PARSERS:
        return _PARSERS[kind](content)
    if kind == "unknown":
        try:
            return parse_image_to_text(content)
        except DocumentParsingError as exc:
            raise DocumentParsingError(
                "Не удалось определить тип файла и извлечь текст (не PDF/DOCX/XLSX/изображение).",
            ) from exc
    raise DocumentParsingError(f"Неподдерживаемый тип содержимого: {kind}")
