# ui/mainwin/text_draft.py — MainWindow 텍스트 초안 모드와 읽기(reflow) 모드 믹스인
# main_window.py에서 순수 이동(behavior 변경 없음)으로 분리됨.
from __future__ import annotations
import os
import sys
from pathlib import Path

from PySide6.QtGui import (
    QAction, QKeySequence, QShortcut, QIcon, QClipboard, QColor,
    QPainter, QPen, QLinearGradient, QRadialGradient, QPainterPath, QPixmap
)
from PySide6.QtCore import Qt, QSize, QTimer, QPointF, QRectF, QRect
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QFileDialog, QMessageBox,
    QStatusBar, QToolBar, QLabel, QComboBox, QSlider,
    QWidget, QHBoxLayout, QDockWidget, QApplication, QPushButton, QSizePolicy,
    QWidgetAction, QStyle, QSpinBox, QStackedWidget, QGraphicsDropShadowEffect,
    QTabWidget, QTabBar,
)

import config as _cfg

from ui.glass_button import GlassButton
from core.document  import PdfDocument
from core.renderer  import PageRenderer
from core.exporter  import Exporter
from ui.canvas_view import PdfCanvasView
from ui.thumbnail_panel import ThumbnailPanel
from ui.clipboard_panel import ClipboardPanel
from ui.note_panel import NotePanel
from ui.text_draft_editor import TextDraftEditor
from ui.reflow_read_view import ReflowReadView
from ui.texts import UI
from utils.settings import AppSettings
from utils.annot_style import apply_settings_defaults


class TextDraftMixin:
    """MainWindow 텍스트 초안 모드와 읽기(reflow) 모드."""


    # ── 파일 동작 ────────────────────────────────────────────────────
    def _enter_text_draft_mode(self):
        self._doc.close()
        self._text_draft.new_document()
        self._text_draft_active = True
        self._central_stack.setCurrentWidget(self._text_draft)
        self._annot_bar.setVisible(False)
        if hasattr(self, "_view_toolbar"):
            self._view_toolbar.setVisible(False)
        if hasattr(self, "_doc_toolbar"):
            self._doc_toolbar.setVisible(False)
        self._page_lbl.setText("")
        self._pending_lbl.setText("")
        self._status_lbl.setText('새 문서 작성 모드')
        self.setWindowTitle(_cfg.window_title('새 문서 작성'))
        self._on_text_draft_cursor_changed(1, 1)


    def _leave_text_draft_mode(self):
        self._text_draft_active = False
        self._central_stack.setCurrentWidget(self._tab_widget)
        self._annot_bar.setVisible(True)
        if hasattr(self, "_view_toolbar"):
            self._view_toolbar.setVisible(True)
        if hasattr(self, "_doc_toolbar"):
            self._doc_toolbar.setVisible(True)


    def _exit_text_draft_mode_requested(self):
        if not self._text_draft_active:
            return
        if not self._confirm_discard():
            return
        self._leave_text_draft_mode()
        self._page_lbl.setText("")
        self._pending_lbl.setText("")
        self._status_lbl.setText(" ")
        self.setWindowTitle(_cfg.window_title())


    def _enter_reflow_mode(self, start_page: int | None = None, force: bool = False):
        if not self._doc.is_open:
            return
        start = self._canvas.current_page() if start_page is None else int(start_page)
        self._reflow_active = True
        self._central_stack.setCurrentWidget(self._reflow_view)
        self._annot_bar.setVisible(False)
        self._reflow_view.load_document(self._doc.fitz_doc(), self._doc.path, start_page=start, force=force)


    def _leave_reflow_mode(self, target_page: int | None = None) -> int:
        page = self._reflow_view.current_page() if target_page is None else int(target_page)
        self._reflow_active = False
        self._central_stack.setCurrentWidget(self._tab_widget)
        self._annot_bar.setVisible(True)
        return max(0, page)


    def _save_text_draft(self, override_path=None) -> bool:
        path = override_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, '다른 이름으로 저장', '', 'PDF 파일 (*.pdf)')
            if not path:
                return False
        if not path.lower().endswith('.pdf'):
            path += '.pdf'
        try:
            self._text_draft.export_pdf(path)
        except Exception as e:
            QMessageBox.critical(self, '저장 오류', str(e))
            return False
        if not self._doc.open(path):
            QMessageBox.critical(self, '오류', f'생성한 PDF를 열 수 없습니다.\n{path}')
            return False
        self._settings.add_recent(path)
        self._settings.save()
        self._status_lbl.setText(f'새 문서 저장 완료: {path}')
        return True


    def _open_as_draft_document(self, html_body: str):
        """DocViewerDialog에서 전달된 HTML을 편집 가능한 새 문서로 열기."""
        if not self._confirm_discard():
            return
        self._enter_text_draft_mode()
        editor = self._text_draft.editor()
        editor.setHtml(html_body)

        # HTML의 폰트 크기가 작을 수 있으므로 전체 텍스트에 기본 크기 적용
        # bold/italic/underline은 mergeCharFormat으로 유지됨
        from PySide6.QtGui import QTextCharFormat, QTextCursor
        base_font = self._text_draft._base_font
        fmt = QTextCharFormat()
        fmt.setFontFamily(base_font.family())
        fmt.setFontPointSize(float(base_font.pointSize()))
        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeCharFormat(fmt)
        cursor.clearSelection()
        editor.setTextCursor(cursor)

        editor.document().setModified(False)
        self._status_lbl.setText('새 문서 작성 모드  -  불러옴')


    def _on_text_draft_cursor_changed(self, line_no: int, col_no: int):
        if self._text_draft_active:
            self._page_lbl.setText(f'줄 {line_no}, 열 {col_no}')


    def _on_text_draft_modified(self, modified: bool):
        if self._text_draft_active:
            state = '수정됨' if modified else '준비'
            self._status_lbl.setText(f'새 문서 작성 모드  -  {state}')

