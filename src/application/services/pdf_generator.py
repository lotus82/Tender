"""
Преобразование ответа LLM (Markdown + фрагменты HTML) в PDF в памяти.

ReportLab + TTFont: основной текст — DejaVu (или Arial на Windows); эмодзи — Noto Symbols2 /
Segoe UI Emoji при наличии. HTML-теги из ответа модели преобразуются в разметку Paragraph,
а не показываются как сырой текст.
"""

from __future__ import annotations

import logging
import os
import re
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import emoji
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

_REGISTERED_TTF: set[str] = set()

_FONT_SEARCH_DIRS = (
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/ttf-dejavu"),
    Path("/usr/share/fonts/TTF"),
)

# Шрифт с расширенными символами / эмодзи (DejaVu покрывает не всё)
def _emoji_font_candidates() -> list[Path]:
    paths: list[Path] = [
        Path("/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoColorEmoji.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
    ]
    windir = os.environ.get("WINDIR", "")
    if windir:
        wf = Path(windir) / "Fonts"
        paths.extend(
            [
                wf / "seguiemj.ttf",
                wf / "SegoeUIEmoji.ttf",
            ],
        )
    return paths


def _resolve_font_paths() -> tuple[Path, Path, Path] | None:
    """Пути к TTF: regular, bold, mono (mono/bold могут совпадать с regular)."""
    for d in _FONT_SEARCH_DIRS:
        s = d / "DejaVuSans.ttf"
        if s.is_file():
            b = d / "DejaVuSans-Bold.ttf"
            m = d / "DejaVuSansMono.ttf"
            return (s, b if b.is_file() else s, m if m.is_file() else s)
    windir = os.environ.get("WINDIR", "")
    if windir:
        wf = Path(windir) / "Fonts"
        s = wf / "DejaVuSans.ttf"
        if s.is_file():
            b = wf / "DejaVuSans-Bold.ttf"
            m = wf / "DejaVuSansMono.ttf"
            return (s, b if b.is_file() else s, m if m.is_file() else s)
        arial = wf / "arial.ttf"
        if arial.is_file():
            return (arial, arial, arial)
    return None


def _register_ttf_once(name: str, path: Path) -> None:
    if name in _REGISTERED_TTF:
        return
    pdfmetrics.registerFont(TTFont(name, str(path)))
    _REGISTERED_TTF.add(name)


def _register_fonts(sans: Path, bold: Path, mono: Path) -> tuple[str, str, str]:
    """Зарегистрировать TTF в reportlab; вернуть имена шрифтов для Paragraph."""
    _register_ttf_once("TenderSans", sans)
    _register_ttf_once("TenderSans-Bold", bold)
    _register_ttf_once("TenderMono", mono)
    return "TenderSans", "TenderSans-Bold", "TenderMono"


def _register_emoji_font() -> str | None:
    """Подключить шрифт для эмодзи; имя ``TenderEmoji`` или ``None``."""
    for path in _emoji_font_candidates():
        if not path.is_file():
            continue
        try:
            _register_ttf_once("TenderEmoji", path)
            return "TenderEmoji"
        except Exception:
            logger.debug("Шрифт эмодзи не подошёл: %s", path, exc_info=True)
    return None


def _strip_script_style(html: str) -> str:
    s = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.I | re.S)
    s = re.sub(r"<style[^>]*>.*?</style>", "", s, flags=re.I | re.S)
    return s


def _wrap_emojis_plain(plain: str, emoji_face: str | None) -> str:
    """Экранирование XML + эмодзи через отдельный встроенный шрифт."""
    if not plain:
        return ""
    if not emoji_face:
        return escape(plain)
    parts: list[str] = []
    idx = 0
    for em in emoji.emoji_list(plain):
        s, e = em["match_start"], em["match_end"]
        if idx < s:
            parts.append(escape(plain[idx:s]))
        seg = plain[s:e]
        parts.append(f'<font face="{emoji_face}">{escape(seg)}</font>')
        idx = e
    if idx < len(plain):
        parts.append(escape(plain[idx:]))
    return "".join(parts)


def _text_chunk_to_rl(data: str, emoji_face: str | None) -> str:
    """Фрагмент текста между HTML-тегами: ``**md**`` + эмодзи + escape."""
    parts = re.split(r"(\*\*.+?\*\*)", data, flags=re.DOTALL)
    chunks: list[str] = []
    for p in parts:
        if len(p) >= 4 and p.startswith("**") and p.endswith("**"):
            inner = p[2:-2]
            chunks.append("<b>" + _wrap_emojis_plain(inner, emoji_face) + "</b>")
        else:
            chunks.append(_wrap_emojis_plain(p, emoji_face))
    return "".join(chunks).replace("\n", "<br/>")


class _HtmlToReportLab(HTMLParser):
    """Подмножество HTML → разметка Paragraph (b, i, br, a, code, списки)."""

    def __init__(self, emoji_face: str | None, mono_face: str) -> None:
        super().__init__(convert_charrefs=True)
        self.emoji_face = emoji_face
        self.mono_face = mono_face
        self.out: list[str] = []
        self._code_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        ad = {k.lower(): (v or "") for k, v in attrs}

        if t in ("br", "br/"):
            self.out.append("<br/>")
            return
        if t == "strong":
            self.out.append("<b>")
            return
        if t == "b":
            self.out.append("<b>")
            return
        if t in ("em", "i"):
            self.out.append("<i>")
            return
        if t == "u":
            self.out.append("<u>")
            return
        if t == "p":
            if self.out:
                self.out.append("<br/>")
            return
        if t in ("code", "pre"):
            self._code_depth += 1
            self.out.append(f'<font face="{self.mono_face}" size="9">')
            return
        if t == "a":
            href = ad.get("href", "")
            if href:
                self.out.append(f"<a href={quoteattr(href)} color=\"blue\">")
            else:
                self.out.append('<a color="blue">')
            return
        if t == "li":
            self.out.append("<br/>• ")
            return
        if t in ("ul", "ol", "div", "blockquote", "section", "article"):
            return
        if t == "h1":
            self.out.append('<b><font size="16">')
            return
        if t == "h2":
            self.out.append('<b><font size="14">')
            return
        if t == "h3":
            self.out.append('<b><font size="12">')
            return
        if t == "h4":
            self.out.append('<b><font size="11">')
            return

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("strong", "b"):
            self.out.append("</b>")
            return
        if t in ("em", "i"):
            self.out.append("</i>")
            return
        if t == "u":
            self.out.append("</u>")
            return
        if t == "p":
            self.out.append("<br/>")
            return
        if t in ("code", "pre"):
            if self._code_depth:
                self._code_depth -= 1
            self.out.append("</font>")
            return
        if t == "a":
            self.out.append("</a>")
            return
        if t in ("h1", "h2", "h3", "h4"):
            self.out.append("</font></b>")
            return

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self.out.append(_text_chunk_to_rl(data, self.emoji_face))


def _html_mixed_to_rl_markup(fragment: str, *, emoji_face: str | None, mono_face: str) -> str:
    fragment = _strip_script_style(fragment.strip())
    if not fragment:
        return escape(" ")
    parser = _HtmlToReportLab(emoji_face, mono_face)
    parser.feed(fragment)
    parser.close()
    return "".join(parser.out) if parser.out else escape(" ")


def _is_table_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    for c in cells:
        s = c.strip().replace(" ", "")
        if not re.fullmatch(r":?-{3,}:?", s):
            return False
    return True


def _parse_markdown_table(block: str) -> list[list[str]] | None:
    lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 2 or not all("|" in ln for ln in lines[:2]):
        return None
    rows: list[list[str]] = []
    for ln in lines:
        raw = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(raw)
    if len(rows) >= 2 and _is_table_separator_row(rows[1]):
        rows.pop(1)
    if not rows:
        return None
    return rows


def _build_story(
    markdown_text: str,
    *,
    font_body: str,
    font_bold: str,
    font_mono: str,
    emoji_face: str | None,
) -> list:
    base = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "TenderBody",
        parent=base["Normal"],
        fontName=font_body,
        fontSize=11,
        leading=14,
        spaceAfter=6,
    )
    h_styles = [
        ParagraphStyle(
            f"TenderH{i}",
            parent=base["Heading1"],
            fontName=font_bold,
            fontSize={1: 16, 2: 14, 3: 12, 4: 11}[i],
            leading={1: 20, 2: 18, 3: 15, 4: 14}[i],
            spaceAfter=8,
            spaceBefore=4,
        )
        for i in range(1, 5)
    ]
    code_style = ParagraphStyle(
        "TenderCode",
        parent=base["Code"],
        fontName=font_mono,
        fontSize=9,
        leading=11,
        leftIndent=6,
        spaceAfter=8,
    )
    cell_style = ParagraphStyle(
        "TenderCell",
        parent=body_style,
        fontSize=9,
        leading=11,
    )
    head_cell_style = ParagraphStyle(
        "TenderHeadCell",
        parent=cell_style,
        fontName=font_bold,
    )

    story: list = []
    md = markdown_text.strip() or "(пусто)"
    blocks = re.split(r"\n{2,}", md)

    for block in blocks:
        b = block.strip()
        if not b:
            continue

        if b.startswith("```"):
            lines = b.split("\n")
            code_lines = lines[1:-1] if len(lines) > 2 else lines[1:]
            code_text = "\n".join(code_lines) if code_lines else ""
            story.append(Preformatted(code_text or " ", code_style, maxLineLength=100))
            story.append(Spacer(1, 4))
            continue

        m = re.match(r"^(#{1,4})\s+(.+)$", b, re.DOTALL)
        if m:
            level = min(len(m.group(1)), 4)
            inner = m.group(2).strip()
            story.append(
                Paragraph(
                    _html_mixed_to_rl_markup(inner, emoji_face=emoji_face, mono_face=font_mono),
                    h_styles[level - 1],
                ),
            )
            story.append(Spacer(1, 4))
            continue

        tbl = _parse_markdown_table(b)
        if tbl is not None:
            ncols = max(len(r) for r in tbl)
            page_w = A4[0] - 40 * mm
            col_w = page_w / max(ncols, 1)
            norm = [r + [""] * (ncols - len(r)) for r in tbl]
            data: list[list[Paragraph]] = []
            for ri, row in enumerate(norm):
                st = head_cell_style if ri == 0 else cell_style
                data.append(
                    [
                        Paragraph(
                            _html_mixed_to_rl_markup(c, emoji_face=emoji_face, mono_face=font_mono)
                            if c
                            else " ",
                            st,
                        )
                        for c in row
                    ],
                )
            t = Table(data, colWidths=[col_w] * ncols, repeatRows=1)
            t.setStyle(
                TableStyle(
                    [
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ],
                ),
            )
            story.append(t)
            story.append(Spacer(1, 8))
            continue

        story.append(
            Paragraph(
                _html_mixed_to_rl_markup(b, emoji_face=emoji_face, mono_face=font_mono),
                body_style,
            ),
        )

    if not story:
        story.append(Paragraph(escape("(пусто)"), body_style))
    return story


def markdown_response_to_pdf(markdown_text: str) -> BytesIO:
    """
    Собрать PDF из текста ответа модели (Markdown → ReportLab).

    :return: ``BytesIO`` с позицией 0.
    """
    paths = _resolve_font_paths()
    if paths is None:
        logger.error("Не найдены TTF с кириллицей (DejaVu или arial).")
        raise RuntimeError(
            "Не найдены шрифты: установите fonts-dejavu-core в образе или DejaVu/Arial в Windows/Fonts.",
        )

    font_body, font_bold, font_mono = _register_fonts(*paths)
    emoji_face = _register_emoji_font()
    story = _build_story(
        markdown_text,
        font_body=font_body,
        font_bold=font_bold,
        font_mono=font_mono,
        emoji_face=emoji_face,
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title="Результат анализа",
    )
    try:
        doc.build(story)
    except Exception:
        logger.exception("Ошибка сборки PDF (ReportLab)")
        raise
    buffer.seek(0)
    return buffer
