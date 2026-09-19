# ui/mainwin/view_modes.py — MainWindow 보기 모드(책/두 쪽/스크롤)와 줌 믹스인
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
from utils.errlog import swallowed


class ViewModesMixin:
    """MainWindow 보기 모드(책/두 쪽/스크롤)와 줌."""


    def _toggle_book_view(self):
        if not self._doc.is_open:
            return
        if self._reflow_active:
            idx = self._leave_reflow_mode()
            self._canvas.show_page(idx)
        self._book_view_active = not self._book_view_active
        active = self._book_view_active
        self._view_mode = UI.VIEW_BOOK if active else UI.VIEW_SINGLE
        if hasattr(self, '_book_btn'):
            self._book_btn.setChecked(active)
        if hasattr(self, '_view_cb'):
            self._view_cb.blockSignals(True)
            self._view_cb.setCurrentText(self._view_mode)
            self._view_cb.blockSignals(False)
        self._canvas.set_book_view_enabled(active)
        if active:
            self._enter_book_ui()
            left = max(0, self._canvas.current_page())
            if left % 2 == 1:
                left -= 1
            self._canvas.show_double(left)
            QTimer.singleShot(50, self._canvas.fit_width)
        else:
            # 책보기 종료 → 항상 세로 스크롤 모드로 복원
            self._view_mode = UI.VIEW_SCROLL
            if hasattr(self, '_view_cb'):
                self._view_cb.blockSignals(True)
                self._view_cb.setCurrentText(UI.VIEW_SCROLL)
                self._view_cb.blockSignals(False)
            self._restore_book_ui()
            self._canvas.show_scroll()
            # show_scroll() 내부가 책보기 zoom을 그대로 복원하므로 1.0 으로 덮어씀
            QTimer.singleShot(0, lambda: self._canvas.set_zoom(1.0))

    def _restore_book_ui(self):
        """책 보기 종료 시 이전 상태로 UI를 복원."""
        prev = self._book_view_prev or {}
        if prev.get('menubar_visible', True):
            self._menubar.show()
        if prev.get('annot_bar_visible', True):
            self._annot_bar.show()
        if prev.get('view_toolbar_visible', True) and hasattr(self, '_view_toolbar'):
            self._view_toolbar.show()
        if prev.get('doc_toolbar_visible', True) and hasattr(self, '_doc_toolbar'):
            self._doc_toolbar.show()
        if prev.get('statusbar_visible', True):
            self.statusBar().show()
        thumbs_visible = prev.get('thumbs_visible', False)
        prev_sizes = prev.get('splitter_sizes')
        if thumbs_visible:
            self._thumbs.show()
            self._splitter.setSizes(prev_sizes or [180, 1000])
        else:
            self._thumbs.hide()
            self._splitter.setSizes([0, 1])
        if hasattr(self, '_thumbnail_toggle_action'):
            self._thumbnail_toggle_action.setChecked(thumbs_visible)
        # 탭 바 복원 (책보기 전 상태로)
        tabs_were_visible = prev.get('tab_bar_visible', getattr(self._settings, 'tabs_enabled', True))
        if hasattr(self, '_tab_widget'):
            self._tab_widget.tabBar().setVisible(tabs_were_visible)
        if hasattr(self, '_new_tab_btn'):
            self._new_tab_btn.setVisible(tabs_were_visible)
        if prev.get('was_fullscreen', False):
            self.showFullScreen()
        elif prev.get('was_maximized', False):
            self.showMaximized()
        else:
            self.showNormal()
            geometry = prev.get('geometry')
            if geometry:
                self.restoreGeometry(geometry)


    def _enter_book_ui(self):
        tab_bar_visible = (
            hasattr(self, '_tab_widget') and self._tab_widget.tabBar().isVisible()
        )
        self._book_view_prev = {
            'thumbs_visible': self._thumbs.isVisible(),
            'splitter_sizes': self._splitter.sizes(),
            'menubar_visible': self._menubar.isVisible(),
            'annot_bar_visible': self._annot_bar.isVisible(),
            'view_toolbar_visible': self._view_toolbar.isVisible() if hasattr(self, '_view_toolbar') else True,
            'doc_toolbar_visible': self._doc_toolbar.isVisible() if hasattr(self, '_doc_toolbar') else True,
            'statusbar_visible': self.statusBar().isVisible(),
            'was_fullscreen': self.isFullScreen(),
            'was_maximized': self.isMaximized(),
            'geometry': self.saveGeometry(),
            'tab_bar_visible': tab_bar_visible,
            'view_mode': getattr(self, '_view_mode', UI.VIEW_SINGLE),  # 책보기 종료 시 복원용
        }
        self._menubar.hide()
        self._annot_bar.hide()
        if hasattr(self, '_view_toolbar'):
            self._view_toolbar.hide()
        if hasattr(self, '_doc_toolbar'):
            self._doc_toolbar.hide()
        self.statusBar().hide()
        self._thumbs.hide()
        self._splitter.setSizes([0, 1])
        # 책보기 모드에서는 탭 바 숨김
        if hasattr(self, '_tab_widget'):
            self._tab_widget.tabBar().setVisible(False)
        if hasattr(self, '_new_tab_btn'):
            self._new_tab_btn.setVisible(False)

        # 활성 도구를 선택 도구로 리셋 (스탬프 등 우클릭 필요한 도구 해제)
        if hasattr(self._annot_bar, '_tools'):
            sel = self._annot_bar._tools.get('select')
            if sel:
                self._canvas.set_tool(sel)
                self._annot_bar._restore_active_btn()

        self.showFullScreen()

    def _on_view_mode(self, text: str):
        if not self._doc.is_open:
            return
        idx = self._canvas.current_page()
        prev_mode = getattr(self, '_view_mode', UI.VIEW_SINGLE)
        was_book = self._book_view_active
        was_segment = prev_mode == UI.VIEW_SEGMENT
        was_scroll = prev_mode == UI.VIEW_SCROLL
        was_immersive = was_book or was_segment
        leaving_spread = prev_mode in (UI.VIEW_DOUBLE, UI.VIEW_BOOK)
        self._view_mode = text

        if text == UI.VIEW_SINGLE:
            self._book_view_active = False
            if hasattr(self, '_book_btn'):
                self._book_btn.setChecked(False)
            self._canvas.set_book_view_enabled(False)
            if was_immersive:
                self._restore_book_ui()
            self._canvas.show_page(idx)
            if was_segment:
                QTimer.singleShot(0, self._canvas.fit_page)
            elif leaving_spread:
                QTimer.singleShot(0, lambda: self._canvas.set_zoom(1.0))
            elif was_scroll:
                QTimer.singleShot(0, lambda: self._canvas.centerOn(self._canvas.sceneRect().center()))

        elif text == UI.VIEW_DOUBLE:
            self._book_view_active = False
            if hasattr(self, '_book_btn'):
                self._book_btn.setChecked(False)
            self._canvas.set_book_view_enabled(False)
            if was_immersive:
                self._restore_book_ui()
            left = idx - 1 if idx % 2 == 0 else idx
            self._canvas.show_double(max(0, left))
            QTimer.singleShot(0, self._canvas.fit_page)

        elif text == UI.VIEW_SEGMENT:
            self._book_view_active = False
            if hasattr(self, '_book_btn'):
                self._book_btn.setChecked(False)
            if not was_immersive:
                self._enter_book_ui()
            self._canvas.set_book_view_enabled(True)
            self._canvas.show_segment(idx, 0, 2)
            QTimer.singleShot(50, self._canvas.fit_width)

        elif text == UI.VIEW_BOOK:
            if not was_immersive:
                self._enter_book_ui()
            self._book_view_active = True
            if hasattr(self, '_book_btn'):
                self._book_btn.setChecked(True)
            self._canvas.set_book_view_enabled(True)
            left = idx - 1 if idx % 2 == 0 else idx
            self._canvas.show_double(max(0, left))
            QTimer.singleShot(50, self._canvas.fit_width)

        elif text == UI.VIEW_SCROLL:
            self._book_view_active = False
            if hasattr(self, '_book_btn'):
                self._book_btn.setChecked(False)
            self._canvas.set_book_view_enabled(False)
            if was_immersive:
                self._restore_book_ui()
            self._canvas.show_scroll()
            if leaving_spread:
                QTimer.singleShot(0, lambda: self._canvas.set_zoom(1.0))


    def _on_zoom_changed(self, text: str):
        if text == '':
            self._canvas.fit_page()
        elif text == '':
            self._canvas.fit_width()
        elif text == '':
            self._canvas.set_zoom(1.0)
        else:
            try:
                pct = float(text.replace('%', ''))
                self._canvas.set_zoom(pct / 100)
            except ValueError:
                swallowed()

