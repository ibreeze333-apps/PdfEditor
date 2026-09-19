from __future__ import annotations

import html
import re

import fitz
from PySide6.QtCore import QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QTextDocument
from PySide6.QtWidgets import (
    QComboBox,
    QFontComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from utils.errlog import swallowed


_LABEL_FONT = "\uae00\uaf34"
_LABEL_SIZE = "\ud06c\uae30"
_LABEL_WIDTH = "\ud310\ud615"
_LABEL_TONE = "\ud1a4"
_MODE_NAME = "\uc77d\uae30 \ubaa8\ub4dc"
_PAGE_WORD = "\ud398\uc774\uc9c0"
_EMPTY_TITLE = "\ud14d\uc2a4\ud2b8\ub97c \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4."
_EMPTY_DESC = "\ud14d\uc2a4\ud2b8 \uae30\ubc18 PDF\ub97c \uc5f4\uac70\ub098 OCR\uc744 \uba3c\uc800 \uc2e4\ud589\ud574 \uc8fc\uc138\uc694."
_WIDTH_NARROW = "\uc2ac\ub9bc"
_WIDTH_NORMAL = "\ubcf4\ud1b5"
_WIDTH_WIDE = "\ub113\uc74c"
_TONE_BOOK = "\ucc45 \ub290\ub08c"
_TONE_LIGHT = "\ubc1d\uc740"
_TONE_SEPIA = "\uc138\ud53c\uc544"

# 번역 관련 상수
_TRANS_LOADING = "번역 중… 잠시 기다려주세요."


class ReflowReadView(QWidget):
    page_changed = Signal(int)

    _TONES = {
        _TONE_BOOK: {
            "viewport": "#d7c19a",
            "toolbar": "#ecdcbc",
            "paper": "#f9f2e5",
            "paper_edge": "#ccb287",
            "meta": "#8a6a43",
            "text": "#2d251d",
            "title": "#17120e",
            "shadow": QColor(53, 39, 20, 52),
            "gutter_top": "rgba(124, 92, 55, 0.00)",
            "gutter_mid": "rgba(124, 92, 55, 0.22)",
        },
        _TONE_LIGHT: {
            "viewport": "#e8edf6",
            "toolbar": "#f6f8fc",
            "paper": "#ffffff",
            "paper_edge": "#d8dfe9",
            "meta": "#64748b",
            "text": "#1f2937",
            "title": "#111827",
            "shadow": QColor(15, 23, 42, 28),
            "gutter_top": "rgba(100, 116, 139, 0.00)",
            "gutter_mid": "rgba(100, 116, 139, 0.16)",
        },
        _TONE_SEPIA: {
            "viewport": "#d8c09a",
            "toolbar": "#e8d4ae",
            "paper": "#f6e9d3",
            "paper_edge": "#bf9d70",
            "meta": "#7a6140",
            "text": "#31271d",
            "title": "#1c150d",
            "shadow": QColor(62, 43, 21, 46),
            "gutter_top": "rgba(119, 87, 53, 0.00)",
            "gutter_mid": "rgba(119, 87, 53, 0.18)",
        },
    }

    _WIDTHS = {
        _WIDTH_NARROW: 360,
        _WIDTH_NORMAL: 412,
        _WIDTH_WIDE: 452,
    }

    _PAGE_RATIO = 1.54
    _Y_TOL = 3.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: fitz.Document | None = None
        self._doc_key: tuple | None = None
        self._page_count = 0
        self._current_page = 0
        self._line_cache: dict[int, list[dict[str, float | str]]] = {}
        self._segment_cache: dict[int, list[tuple[str, str, float]]] = {}
        self._last_page_size = (0, 0)

        self._font_family = self._default_font_family()
        self._font_size = 22
        self._page_width_name = _WIDTH_NORMAL
        self._tone_name = _TONE_BOOK

        # 번역 상태
        self._translate_mode = False
        self._translate_src = 'en'
        self._translate_tgt = 'ko'
        # key: (page_index, src, tgt) → segments
        self._translated_cache: dict[tuple, list[tuple[str, str, float]]] = {}
        self._translating_pages: set[tuple] = set()
        self._pool = QThreadPool.globalInstance()

        self._toolbar = QFrame(self)
        self._toolbar.setObjectName("reflowToolbar")
        tb_lay = QHBoxLayout(self._toolbar)
        tb_lay.setContentsMargins(18, 14, 18, 14)
        tb_lay.setSpacing(12)

        self._font_label = QLabel(_LABEL_FONT, self._toolbar)
        tb_lay.addWidget(self._font_label)

        self._font_combo = QFontComboBox(self._toolbar)
        try:
            self._font_combo.setWritingSystem(QFontDatabase.WritingSystem.Korean)
        except Exception:
            swallowed()
        self._font_combo.setCurrentFont(QFont(self._font_family))
        self._font_combo.setMinimumWidth(240)
        self._font_combo.currentFontChanged.connect(self._on_font_changed)
        tb_lay.addWidget(self._font_combo)

        self._size_label = QLabel(_LABEL_SIZE, self._toolbar)
        tb_lay.addWidget(self._size_label)

        self._size_spin = QSpinBox(self._toolbar)
        self._size_spin.setRange(14, 40)
        self._size_spin.setValue(self._font_size)
        self._size_spin.setSuffix(" pt")
        self._size_spin.valueChanged.connect(self._on_size_changed)
        tb_lay.addWidget(self._size_spin)

        self._width_label = QLabel(_LABEL_WIDTH, self._toolbar)
        tb_lay.addWidget(self._width_label)

        self._width_combo = QComboBox(self._toolbar)
        self._width_combo.addItems([_WIDTH_NARROW, _WIDTH_NORMAL, _WIDTH_WIDE])
        self._width_combo.setCurrentText(self._page_width_name)
        self._width_combo.currentTextChanged.connect(self._on_width_changed)
        tb_lay.addWidget(self._width_combo)

        self._tone_label = QLabel(_LABEL_TONE, self._toolbar)
        tb_lay.addWidget(self._tone_label)

        self._tone_combo = QComboBox(self._toolbar)
        self._tone_combo.addItems([_TONE_BOOK, _TONE_LIGHT, _TONE_SEPIA])
        self._tone_combo.setCurrentText(self._tone_name)
        self._tone_combo.currentTextChanged.connect(self._on_tone_changed)
        tb_lay.addWidget(self._tone_combo)

        # 구분선
        sep_lbl = QLabel('│')
        sep_lbl.setStyleSheet('color: #b0a090; padding: 0 4px;')
        tb_lay.addWidget(sep_lbl)

        # 번역 토글 버튼
        self._trans_btn = QPushButton('🔤 번역')
        self._trans_btn.setCheckable(True)
        self._trans_btn.setChecked(False)
        self._trans_btn.setToolTip(
            '읽기 보기 번역은 경량화되었습니다.\n'
            '번역 메뉴의 Ollama 번역을 사용하세요.'
        )
        self._trans_btn.clicked.connect(self._on_translate_toggled)
        tb_lay.addWidget(self._trans_btn)

        # 번역 방향 콤보
        from utils.translate_text_utils import LANG_PAIRS as _LANG_PAIRS
        self._trans_lang_cb = QComboBox()
        self._trans_lang_cb.addItems(list(_LANG_PAIRS.keys()))
        self._trans_lang_cb.setCurrentText('영어 → 한국어')
        self._trans_lang_cb.setToolTip('번역 방향')
        self._trans_lang_cb.currentTextChanged.connect(self._on_translate_lang_changed)
        tb_lay.addWidget(self._trans_lang_cb)

        # 번역 상태 레이블
        self._trans_status_lbl = QLabel('')
        self._trans_status_lbl.setStyleSheet(
            'color: #64748b; font-size: 11px; font-weight: 400;'
        )
        tb_lay.addWidget(self._trans_status_lbl)

        tb_lay.addStretch(1)

        self._stage = QFrame(self)
        self._stage.setObjectName("reflowStage")
        stage_lay = QHBoxLayout(self._stage)
        stage_lay.setContentsMargins(26, 24, 26, 26)
        stage_lay.setSpacing(0)
        stage_lay.addStretch(1)

        self._spread = QFrame(self._stage)
        self._spread.setObjectName("reflowSpread")
        spread_lay = QHBoxLayout(self._spread)
        spread_lay.setContentsMargins(0, 0, 0, 0)
        spread_lay.setSpacing(26)

        self._left_shell, self._left_browser, self._left_footer = self._build_page_shell("left")
        self._right_shell, self._right_browser, self._right_footer = self._build_page_shell("right")

        self._gutter = QFrame(self._spread)
        self._gutter.setObjectName("reflowGutter")
        self._gutter.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._gutter.setFixedWidth(34)

        spread_lay.addWidget(self._left_shell)
        spread_lay.addWidget(self._gutter, 0, Qt.AlignmentFlag.AlignVCenter)
        spread_lay.addWidget(self._right_shell)

        stage_lay.addWidget(self._spread, 0, Qt.AlignmentFlag.AlignCenter)
        stage_lay.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._toolbar)
        lay.addWidget(self._stage, 1)

        self._apply_tone_styles()
        self._refresh_spread_geometry()

    def _build_page_shell(self, side: str):
        shell = QFrame(self._spread)
        shell.setObjectName("reflowPageShell")
        shell.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        shadow = QGraphicsDropShadowEffect(shell)
        shadow.setBlurRadius(38)
        shadow.setOffset(0, 14)
        shell.setGraphicsEffect(shadow)

        lay = QVBoxLayout(shell)
        lay.setContentsMargins(32, 28, 32, 20)
        lay.setSpacing(10)

        browser = QTextBrowser(shell)
        browser.setObjectName(f"reflowBrowser_{side}")
        browser.setReadOnly(True)
        browser.setFrameShape(QFrame.Shape.NoFrame)
        browser.setOpenExternalLinks(False)
        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.document().setDocumentMargin(0)
        lay.addWidget(browser, 1)

        footer = QLabel(shell)
        footer.setObjectName(f"reflowFooter_{side}")
        footer.setAlignment(Qt.AlignmentFlag.AlignLeft if side == "left" else Qt.AlignmentFlag.AlignRight)
        lay.addWidget(footer)
        return shell, browser, footer

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_spread_geometry()

    def clear_document(self):
        self._doc = None
        self._doc_key = None
        self._page_count = 0
        self._current_page = 0
        self._line_cache.clear()
        self._segment_cache.clear()
        self._translated_cache.clear()
        self._translating_pages.clear()
        self._left_browser.clear()
        self._right_browser.clear()
        self._left_footer.clear()
        self._right_footer.clear()

    def page_count(self) -> int:
        return self._page_count

    def current_page(self) -> int:
        return self._current_page

    def load_document(self, fitz_doc: fitz.Document | None, path: str = "", start_page: int = 0, force: bool = False):
        if fitz_doc is None:
            self.clear_document()
            return
        doc_key = (path or "", fitz_doc.page_count, id(fitz_doc))
        if force or doc_key != self._doc_key:
            self._doc_key = doc_key
            self._doc = fitz_doc
            self._page_count = fitz_doc.page_count
            self._line_cache.clear()
            self._segment_cache.clear()
            self._translated_cache.clear()
            self._translating_pages.clear()
        self.go_to_page(start_page)

    def go_to_page(self, page_index: int):
        if self._doc is None or self._page_count <= 0:
            return
        left_index = max(0, min(self._page_count - 1, int(page_index)))
        if left_index % 2 == 1:
            left_index -= 1
        self._current_page = left_index
        self._render_spread(left_index)
        self.page_changed.emit(left_index)

    def prev_page(self):
        self.go_to_page(self._current_page - 2)

    def next_page(self):
        self.go_to_page(self._current_page + 2)

    def _default_font_family(self) -> str:
        db = QFontDatabase()
        families = set(db.families())
        for name in (
            "NanumMyeongjo",
            "Noto Serif KR",
            "Malgun Gothic",
            "NanumGothic",
        ):
            if name in families:
                return name
        return QFont().defaultFamily() or "Malgun Gothic"

    def _invalidate_render(self):
        if self._page_count > 0:
            self.go_to_page(self._current_page)

    def _refresh_spread_geometry(self):
        available_w = max(860, self._stage.width() - 80)
        available_h = max(560, self._stage.height() - 64)
        desired_page_w = self._WIDTHS[self._page_width_name]
        gutter = self._gutter.width() + 26
        max_w_from_total = int((available_w - gutter) / 2)
        max_w_from_height = int(available_h / self._PAGE_RATIO)
        page_w = max(330, min(desired_page_w, max_w_from_total, max_w_from_height))
        page_h = max(500, min(available_h, int(page_w * self._PAGE_RATIO)))
        new_size = (page_w, page_h)

        self._left_shell.setFixedSize(page_w, page_h)
        self._right_shell.setFixedSize(page_w, page_h)
        self._gutter.setFixedHeight(max(220, page_h - 70))
        self._spread.setFixedSize(page_w * 2 + gutter, page_h)

        if new_size != self._last_page_size:
            self._last_page_size = new_size
            if self._page_count > 0:
                QTimer.singleShot(0, lambda: self.go_to_page(self._current_page))

    def _content_size(self, browser: QTextBrowser, fallback_w: int, fallback_h: int) -> tuple[int, int]:
        width = browser.viewport().width()
        height = browser.viewport().height()
        if width <= 0 or height <= 0:
            width = fallback_w
            height = fallback_h
        return width, height

    def _on_font_changed(self, font: QFont):
        family = font.family().strip()
        if family:
            self._font_family = family
            self._invalidate_render()

    def _on_size_changed(self, value: int):
        self._font_size = int(value)
        self._invalidate_render()

    def _on_width_changed(self, text: str):
        if text in self._WIDTHS:
            self._page_width_name = text
            self._refresh_spread_geometry()
            self._invalidate_render()

    def _on_tone_changed(self, text: str):
        if text in self._TONES:
            self._tone_name = text
            self._apply_tone_styles()
            self._invalidate_render()

    def _apply_tone_styles(self):
        tone = self._TONES[self._tone_name]
        for shell in (self._left_shell, self._right_shell):
            effect = shell.graphicsEffect()
            if isinstance(effect, QGraphicsDropShadowEffect):
                effect.setColor(tone["shadow"])
        self.setStyleSheet(
            "#reflowToolbar {"
            f" background: {tone['toolbar']};"
            " border-bottom: 1px solid rgba(80, 60, 30, 0.10);"
            "}"
            "QLabel {"
            " color: #3a3127; font-size: 12px; font-weight: 700;"
            "}"
            "QComboBox, QSpinBox, QFontComboBox {"
            " min-height: 30px; padding: 4px 10px; border-radius: 8px;"
            " border: 1px solid rgba(95, 74, 44, 0.18); background: rgba(255,255,255,0.92);"
            " color: #2c241c;"
            "}"
            "QPushButton {"
            " min-height: 28px; padding: 2px 10px; border-radius: 7px;"
            " border: 1px solid rgba(95, 74, 44, 0.22); background: rgba(255,255,255,0.80);"
            " color: #2c241c; font-size: 12px;"
            "}"
            "QPushButton:checked {"
            " background: #4e7cff; color: #fff; border-color: #3a60d8;"
            "}"
            "QPushButton:hover:!checked {"
            " background: rgba(255,255,255,0.96);"
            "}"
            "#reflowStage {"
            f" background: {tone['viewport']};"
            "}"
            "#reflowSpread {"
            " background: transparent;"
            "}"
            "#reflowPageShell {"
            f" background: {tone['paper']};"
            f" border: 1px solid {tone['paper_edge']};"
            " border-radius: 18px;"
            "}"
            "#reflowGutter {"
            " border: none;"
            " border-radius: 16px;"
            f" background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f" stop:0 {tone['gutter_top']},"
            f" stop:0.5 {tone['gutter_mid']},"
            f" stop:1 {tone['gutter_top']});"
            "}"
            "#reflowFooter_left, #reflowFooter_right {"
            f" color: {tone['meta']};"
            " font-size: 12px; font-weight: 800; letter-spacing: 0.08em;"
            "}"
            "#reflowBrowser_left, #reflowBrowser_right {"
            " background: transparent; border: none; color: #1f2937;"
            "}"
        )

    def _render_spread(self, left_index: int):
        right_index = left_index + 1 if left_index + 1 < self._page_count else None
        if self._translate_mode:
            left_segments  = self._get_translated_segments(left_index)
            right_segments = self._get_translated_segments(right_index) if right_index is not None else []
        else:
            left_segments  = self._extract_page_segments(left_index)
            right_segments = self._extract_page_segments(right_index) if right_index is not None else []

        fallback_w = max(240, self._left_shell.width() - 72)
        fallback_h = max(320, self._left_shell.height() - 84)
        content_w, content_h = self._content_size(self._left_browser, fallback_w, fallback_h)

        left_scale = self._fit_scale_for_page(left_segments, content_w, content_h)
        right_scale = self._fit_scale_for_page(right_segments, content_w, content_h) if right_segments else 1.0

        self._left_browser.setHtml(self._compose_html(left_segments, left_scale))
        self._right_browser.setHtml(
            self._compose_html(right_segments, right_scale) if right_segments else self._blank_page_html()
        )
        self._left_browser.moveCursor(self._left_browser.textCursor().MoveOperation.Start)
        self._right_browser.moveCursor(self._right_browser.textCursor().MoveOperation.Start)
        self._left_footer.setText(str(left_index + 1))
        self._right_footer.setText(str(right_index + 1) if right_index is not None else "")

    def _fit_scale_for_page(self, segments, content_w: int, content_h: int) -> float:
        if not segments:
            return 1.0
        high = 1.0
        if self._measure_html_height(self._compose_html(segments, high), content_w) <= content_h:
            return high
        low = 0.34
        for _ in range(12):
            mid = (low + high) / 2.0
            if self._measure_html_height(self._compose_html(segments, mid), content_w) <= content_h:
                low = mid
            else:
                high = mid
        return low

    def _measure_html_height(self, html_text: str, content_w: int) -> float:
        doc = QTextDocument()
        doc.setHtml(html_text)
        doc.setTextWidth(max(240, content_w))
        return float(doc.size().height())

    def _compose_html(self, segments, scale: float) -> str:
        tone = self._TONES[self._tone_name]
        font_css = self._font_family.replace('"', '\\"')
        base_font = max(14, int(self._font_size * scale))
        title_font = max(21, int(self._font_size * 1.24 * scale))
        section_font = max(17, int(self._font_size * 1.06 * scale))
        subtitle_font = max(15, int(self._font_size * 0.92 * scale))
        note_font = max(13, int(self._font_size * 0.86 * scale))
        line_height = round(1.70 + min(0.16, (self._font_size - 18) * 0.012), 2)

        if not segments:
            body = (
                f'<h1 class="chapter">{_EMPTY_TITLE}</h1>'
                f'<p class="note">{_EMPTY_DESC}</p>'
            )
        else:
            parts: list[str] = []
            prev_kind = ""
            for kind, text, font_size in segments:
                safe = html.escape(text)
                if kind == "title":
                    tag = "h1" if prev_kind == "" else "h2"
                    klass = "chapter" if tag == "h1" else "section"
                    parts.append(f'<{tag} class="{klass}">{safe}</{tag}>')
                elif kind == "subtitle":
                    parts.append(f"<h3>{safe}</h3>")
                else:
                    size_px = max(
                        base_font - 1,
                        min(base_font + 4, int((self._font_size + (font_size - 11.0) * 0.24) * scale)),
                    )
                    klass = "para first" if prev_kind in ("", "title", "subtitle") else "para"
                    parts.append(f'<p class="{klass}" style="font-size:{size_px}px">{safe}</p>')
                prev_kind = kind
            body = "".join(parts)

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
  margin: 0;
  background: transparent;
  color: {tone['text']};
  font-family: \"{font_css}\", \"NanumMyeongjo\", \"Noto Serif KR\", \"Malgun Gothic\", serif;
}}
h1.chapter {{
  margin: 0 0 18px;
  font-size: {title_font}px;
  line-height: 1.22;
  font-weight: 800;
  text-align: center;
  color: {tone['title']};
  letter-spacing: 0.04em;
}}
h2.section {{
  margin: 14px 0 12px;
  font-size: {section_font}px;
  line-height: 1.30;
  font-weight: 800;
  color: {tone['title']};
}}
h3 {{
  margin: 10px 0 8px;
  font-size: {subtitle_font}px;
  line-height: 1.30;
  font-weight: 700;
  color: {tone['title']};
}}
p.para {{
  margin: 0 0 0.80em;
  line-height: {line_height};
  text-align: justify;
  text-indent: 1.5em;
  word-break: keep-all;
  letter-spacing: 0.01em;
  color: {tone['text']};
}}
p.first {{
  text-indent: 0;
}}
p.note {{
  margin: 0;
  font-size: {note_font}px;
  line-height: 1.65;
  color: #6b7280;
}}
</style>
</head>
<body>
{body}
</body>
</html>"""

    def _blank_page_html(self) -> str:
        return """<!DOCTYPE html>
<html>
<head>
<meta charset=\"utf-8\">
</head>
<body></body>
</html>"""

    def _extract_page_segments(self, page_index: int | None) -> list[tuple[str, str, float]]:
        if page_index is None or self._doc is None or page_index < 0 or page_index >= self._page_count:
            return []
        cached = self._segment_cache.get(page_index)
        if cached is not None:
            return cached

        lines = self._extract_page_lines(page_index)
        segments: list[tuple[str, str, float]] = []
        para_parts: list[dict[str, float | str | bool]] = []
        para_font = 11.0
        para_x0 = 0.0
        prev_y1 = 0.0
        prev_font = 11.0

        def flush_para():
            nonlocal para_parts, para_font, para_x0, prev_y1, prev_font
            if para_parts:
                text = self._merge_paragraph_parts(para_parts)
                if text:
                    segments.append(("paragraph", text, para_font))
            para_parts = []
            para_font = 11.0
            para_x0 = 0.0
            prev_y1 = 0.0
            prev_font = 11.0

        for line in lines:
            text = str(line["text"]).strip()
            font = float(line["font"])
            x0 = float(line["x0"])
            y0 = float(line["y0"])
            y1 = float(line["y1"])
            kind = self._segment_kind(text, font)
            if kind != "paragraph":
                flush_para()
                segments.append((kind, text, font))
                continue

            line_info = {
                "text": text,
                "lead_space": bool(line.get("lead_space", False)),
                "trail_space": bool(line.get("trail_space", False)),
            }

            if not para_parts:
                para_parts = [line_info]
                para_font = font
                para_x0 = x0
                prev_y1 = y1
                prev_font = font
                continue

            gap = y0 - prev_y1
            similar_size = abs(font - prev_font) <= 2.2
            similar_indent = abs(x0 - para_x0) <= max(18.0, prev_font * 1.10)
            prev_text = str(para_parts[-1]["text"])
            short_block = len(text) <= 8 or len(prev_text) <= 8
            if gap <= max(prev_font * 1.00, 18.0) and similar_size and similar_indent and not short_block:
                para_parts.append(line_info)
                prev_y1 = y1
                prev_font = font
            else:
                flush_para()
                para_parts = [line_info]
                para_font = font
                para_x0 = x0
                prev_y1 = y1
                prev_font = font

        flush_para()
        self._segment_cache[page_index] = segments
        return segments

    def _extract_page_lines(self, page_index: int) -> list[dict[str, float | str]]:
        cached = self._line_cache.get(page_index)
        if cached is not None:
            return cached
        if self._doc is None:
            return []
        try:
            page = self._doc[page_index]
            raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        except Exception:
            return []

        chars: list[dict[str, float | str]] = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []) or []:
                    fs = float(span.get("size") or 11.0)
                    for ch in span.get("chars", []) or []:
                        c = str(ch.get("c", ""))
                        if not c or c in ("\n", "\r", "\x00"):
                            continue
                        c = (
                            c.replace("\u00a0", " ")
                            .replace("\u2007", " ")
                            .replace("\u202f", " ")
                            .replace("\ufeff", "")
                        )
                        if not c:
                            continue
                        bbox = ch.get("bbox")
                        if not bbox or len(bbox) < 4:
                            continue
                        x0, y0, x1, y1 = map(float, bbox[:4])
                        chars.append({
                            "x0": x0,
                            "x1": x1,
                            "y0": y0,
                            "y1": y1,
                            "ymid": (y0 + y1) / 2.0,
                            "char": c,
                            "font": fs,
                        })

        if not chars:
            self._line_cache[page_index] = []
            return []

        chars.sort(key=lambda item: (float(item["ymid"]), float(item["x0"])))
        buckets: list[list] = []
        for item in chars:
            placed = False
            for bucket in reversed(buckets):
                if abs(float(bucket[0]) - float(item["ymid"])) <= self._Y_TOL:
                    bucket[1].append(item)
                    placed = True
                    break
            if not placed:
                buckets.append([float(item["ymid"]), [item]])

        lines: list[dict[str, float | str | bool]] = []
        for _, bucket_chars in sorted(buckets, key=lambda entry: entry[0]):
            ordered = sorted(bucket_chars, key=lambda item: float(item["x0"]))
            parts: list[str] = []
            x0 = float(ordered[0]["x0"])
            y0 = min(float(item["y0"]) for item in ordered)
            y1 = max(float(item["y1"]) for item in ordered)
            max_font = max(float(item["font"]) for item in ordered)

            for idx, item in enumerate(ordered):
                char = str(item["char"])
                if idx > 0:
                    prev = ordered[idx - 1]
                    prev_w = max(float(prev["x1"]) - float(prev["x0"]), float(prev["font"]) * 0.45, 1.0)
                    gap = float(item["x0"]) - float(prev["x1"])
                    if gap > prev_w * 0.40 and parts and parts[-1] != " " and char != " ":
                        parts.append(" ")
                if char == " ":
                    if parts and parts[-1] != " ":
                        parts.append(" ")
                else:
                    parts.append(char)

            raw_line = "".join(parts)
            leading_space = bool(raw_line[:1].isspace())
            trailing_space = bool(raw_line[-1:].isspace())
            line_text = re.sub(r"[ \t\u00a0]+", " ", raw_line).strip()
            line_text = self._normalize_line_text(line_text)
            if not line_text:
                continue
            lines.append({
                "text": line_text,
                "font": max_font,
                "x0": x0,
                "y0": y0,
                "y1": y1,
                "lead_space": leading_space,
                "trail_space": trailing_space,
            })

        lines.sort(key=lambda item: (round(float(item["y0"]), 2), float(item["x0"])))
        self._line_cache[page_index] = lines
        return lines

    def _merge_paragraph_parts(self, parts: list[dict[str, float | str | bool]]) -> str:
        merged = ""
        prev_trail_space = False
        for part in parts:
            frag = str(part.get("text", "")).strip()
            if not frag:
                continue
            lead_space = bool(part.get("lead_space", False))
            if not merged:
                merged = frag
                prev_trail_space = bool(part.get("trail_space", False))
                continue
            prev = merged[-1]
            curr = frag[0]
            if lead_space or prev_trail_space or self._needs_join_space(prev, curr):
                merged += " "
            merged += frag
            prev_trail_space = bool(part.get("trail_space", False))
        merged = re.sub(r"\s+", " ", merged).strip()
        merged = re.sub(r"([\uac00-\ud7a3A-Za-z0-9])\s+(\uc740|\ub294|\uac00|\uc744|\ub97c|\uc758|\ub3c4|\ub9cc|\uacfc|\uc640|\ub85c|\uc5d0|\uc5d4|\uaed8|\ub791)\b", r"\1\2", merged)
        return merged

    def _needs_join_space(self, prev: str, curr: str) -> bool:
        if prev in ("(", "[", "{", '"', "'"):
            return False
        if curr in (".", ",", ":", ";", "!", "?", ")", "]", "}", '"', "'"):
            return False
        return True

    def _normalize_line_text(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        if re.fullmatch(r"[가-힣](?:\s+[가-힣]){2,}", text):
            text = text.replace(" ", "")
        visible = [ch for ch in text if not ch.isspace()]
        if visible:
            jamo = sum(1 for ch in visible if "ㄱ" <= ch <= "ㆎ")
            if jamo / len(visible) >= 0.55:
                return ""
        text = re.sub(r"\s*[•·]+\s*", " ", text)
        text = re.sub(r"[:]{2,}$", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _segment_kind(self, text: str, font_size: float) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        if not compact:
            return "paragraph"
        if len(compact) <= 26 and font_size >= 16.0:
            return "title"
        if re.match(r"^\d+\.", compact):
            return "subtitle"
        if re.match(r"^[IVX]+\.", compact):
            return "subtitle"
        if re.match(r"^[\uac00-\ud7a3]\.", compact):
            return "subtitle"
        if re.match(r"^\uc81c\s*\d+\s*[\uc7a5\uc808\ud3b8\ubd80]", compact):
            return "subtitle"
        if len(compact) <= 34 and font_size >= 13.5:
            return "subtitle"
        return "paragraph"

    # ── 번역 기능 ─────────────────────────────────────────────────────

    def _on_translate_toggled(self, checked: bool):
        """번역 토글 버튼 클릭."""
        self._translate_mode = checked
        if checked:
            self._update_translate_lang()
            self._trans_status_lbl.setText('번역 준비 중…')
        else:
            self._trans_status_lbl.setText('')
        if self._page_count > 0:
            self.go_to_page(self._current_page)

    def _on_translate_lang_changed(self, text: str):
        """번역 방향 변경 → 캐시 초기화 후 재번역."""
        self._update_translate_lang()
        self._translated_cache.clear()
        self._translating_pages.clear()
        self._trans_status_lbl.setText('')
        if self._translate_mode and self._page_count > 0:
            self.go_to_page(self._current_page)

    def _update_translate_lang(self):
        """현재 콤보 값으로 src/tgt를 갱신한다."""
        try:
            from utils.translate_text_utils import LANG_PAIRS
            pair = LANG_PAIRS.get(self._trans_lang_cb.currentText(), ('en', 'ko'))
            self._translate_src, self._translate_tgt = pair
        except Exception:
            self._translate_src, self._translate_tgt = 'en', 'ko'

    def _get_translated_segments(self, page_index: int | None) -> list[tuple[str, str, float]]:
        """번역된 세그먼트를 반환한다. 아직 없으면 백그라운드 번역을 시작하고 로딩 표시를 반환."""
        if page_index is None:
            return []
        key = (page_index, self._translate_src, self._translate_tgt)
        if key in self._translated_cache:
            return self._translated_cache[key]
        if key not in self._translating_pages:
            self._start_translate_page(page_index)
        return [("paragraph", _TRANS_LOADING, 11.0)]

    def _extract_page_plain_text(self, page_index: int) -> str:
        """번역용 평문 텍스트 추출 (세그먼트 조인)."""
        segments = self._extract_page_segments(page_index)
        if not segments:
            return ''
        parts = [text for _, text, _ in segments if text.strip()]
        return '\n\n'.join(parts)

    def _start_translate_page(self, page_index: int):
        """페이지 텍스트를 백그라운드에서 번역한다."""
        key = (page_index, self._translate_src, self._translate_tgt)
        self._translating_pages.add(key)
        msg = '읽기 보기의 내장 오프라인 번역은 경량화로 제거되었습니다. 번역 메뉴의 Ollama 번역을 사용하세요.'
        self._translated_cache[key] = [("paragraph", msg, 11.0)]
        self._translating_pages.discard(key)
        self._trans_status_lbl.setText('Ollama 번역 메뉴 사용')
        if page_index in (self._current_page, self._current_page + 1):
            self._render_spread(self._current_page)

    def _on_page_translated(self, page_index: int, key: tuple, result: str):
        """번역 완료 — 결과를 캐시에 저장하고 현재 화면이면 재렌더링."""
        self._translating_pages.discard(key)

        # 번역 결과 → 세그먼트 변환
        segs: list[tuple[str, str, float]] = []
        for block in result.split('\n\n'):
            for line in block.split('\n'):
                line = line.strip()
                if line:
                    segs.append(("paragraph", line, 11.0))
        self._translated_cache[key] = segs

        # 진행 상태 갱신
        remaining = len(self._translating_pages)
        if remaining == 0:
            self._trans_status_lbl.setText('✅ 번역 완료')
        else:
            self._trans_status_lbl.setText(f'번역 중… ({remaining}페이지 대기)')

        # 현재 화면인 경우 재렌더링
        if self._translate_mode and page_index in (self._current_page, self._current_page + 1):
            self._render_spread(self._current_page)

    def _on_translate_error(self, key: tuple, err: str):
        """번역 오류 처리."""
        page_index = key[0]
        self._translating_pages.discard(key)
        self._translated_cache[key] = [("paragraph", f'⚠ 번역 오류: {err[:200]}', 11.0)]
        self._trans_status_lbl.setText(f'⚠ 오류: {err[:60]}')
        if self._translate_mode and page_index in (self._current_page, self._current_page + 1):
            self._render_spread(self._current_page)
