# ui/mainwin/edit_ops.py — MainWindow 텍스트 편집/바꾸기/환경설정/undo/pending 적용 믹스인
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


class EditOpsMixin:
    """MainWindow 텍스트 편집/바꾸기/환경설정/undo/pending 적용."""


    # ── 일반 텍스트 에디터 ────────────────────────────────────────────────
    def _open_text_editor(self):
        """독립 텍스트 에디터 창 열기 (메모장 스타일, 비모달)."""
        from ui.dialogs.simple_text_editor import SimpleTextEditor
        if self._simple_text_editor is None:
            ed = SimpleTextEditor(parent=None)
            ed.destroyed.connect(lambda *_: setattr(self, '_simple_text_editor', None))
            self._simple_text_editor = ed
        self._simple_text_editor.show()
        self._simple_text_editor.raise_()
        self._simple_text_editor.activateWindow()


    def _text_editor(self):
        if not self._doc.is_open:
            return
        from ui.dialogs.text_editor_dialog import TextEditorDialog
        dlg = TextEditorDialog(
            self._doc.fitz_doc(),
            self._canvas.current_page(), self)
        dlg.exec()
        if dlg.was_applied():
            self._doc.mark_dirty()
            self._renderer.invalidate_all()
            self._canvas.refresh_page()
            self._status_lbl.setText('텍스트 수정 완료 — 저장해 주세요.')


    # ── 텍스트 찾아 교체 ────────────────────────────────────────────────
    def _text_replace(self):
        if not self._doc.is_open:
            return
        from ui.dialogs.text_replace_dialog import TextReplaceDialog
        dlg = TextReplaceDialog(
            self._doc.fitz_doc(),
            self._canvas.current_page(), self)
        dlg.exec()
        if dlg.replaced_count() > 0:
            self._doc.mark_dirty()
            self._renderer.invalidate_all()
            self._canvas.refresh_page()
            self._status_lbl.setText(
                f'텍스트 {dlg.replaced_count()}군데 교체 완료 — 저장해 주세요.')


    def _apply_save_settings(self):
        """저장 관련 설정을 열려 있는 모든 문서에 반영한다.

        탭마다 PdfDocument 가 따로 있으므로 전부 갱신해야 한다 — 현재 탭만
        바꾸면 다른 탭에서 저장할 때 옛 설정이 그대로 쓰인다.
        """
        subset = bool(getattr(self._settings, 'subset_fonts', True))
        docs = [getattr(t, 'doc', None) for t in getattr(self, '_tabs', [])]
        docs.append(getattr(self, '_doc', None))
        for d in docs:
            if d is not None:
                d.subset_fonts_enabled = subset

    # ── 기본 설정 ────────────────────────────────────────────────────────
    def _open_preferences(self):
        from ui.dialogs.preferences_dialog import PreferencesDialog
        dlg = PreferencesDialog(self._settings, self)
        if dlg.exec():
            self._canvas.set_settings(self._settings)
            self._apply_save_settings()
            self._apply_dict_settings()
            if self._dict_window is not None:
                if hasattr(self._dict_window, '_apply_font'):
                    self._dict_window._apply_font()
                if hasattr(self._dict_window, 'reload_sources'):
                    self._dict_window.reload_sources()


    # ── 보기 ─────────────────────────────────────────────────────────
    def _undo(self):
        if self._text_draft_active:
            self._text_draft.editor().undo()
            return
        if not self._doc.is_open:
            return
        self._canvas.undo_last_annot()


    def _apply_pending(self):
        if not self._doc.is_open:
            return
        if not self._canvas.commit_all_pending():
            QMessageBox.warning(
                self,
                '적용 오류',
                '일부 미확정 어노테이션을 PDF에 적용하지 못했습니다. 문제 항목을 확인한 뒤 다시 시도하세요.',
            )


    def _discard_pending(self):
        if not self._doc.is_open:
            return
        self._canvas.discard_all_pending()

