# ui/mainwin/tabs.py — MainWindow 탭 생성/닫기/전환 믹스인
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


class _DocTab:
    """탭 하나에 대응하는 문서·렌더러·캔버스·썸네일·스플리터 묶음."""
    __slots__ = ('doc', 'renderer', 'canvas', 'thumbs', 'splitter', 'source',
                 'temp_path', 'signals_connected')

    def __init__(self, doc, renderer, canvas, thumbs, splitter, source='pdf', temp_path=''):
        self.doc      = doc
        self.renderer = renderer
        self.canvas   = canvas
        self.thumbs   = thumbs
        self.splitter = splitter
        self.source   = source
        self.temp_path = temp_path
        self.signals_connected = False   # 연결 전 disconnect 시도로 인한 경고 방지


class TabsMixin:
    """MainWindow 탭 생성/닫기/전환."""


    def _attach_tab_close_btn(self, idx: int):
        """탭에 × 닫기 버튼을 붙인다."""
        btn = QPushButton('×')
        btn.setStyleSheet(self._TAB_CLOSE_BTN_STYLE)
        btn.setToolTip('탭 닫기')
        btn.clicked.connect(lambda: self._close_tab_by_btn(btn))
        self._tab_widget.tabBar().setTabButton(idx, QTabBar.ButtonPosition.RightSide, btn)


    def _close_tab_by_btn(self, btn: 'QPushButton'):
        """× 버튼으로 탭 닫기 — 버튼이 속한 탭 인덱스를 찾아서 닫는다."""
        bar = self._tab_widget.tabBar()
        for i in range(bar.count()):
            w = bar.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if w is btn:
                self._close_tab(i)
                return


    def _make_tab(self) -> '_DocTab':
        """새 _DocTab(doc·renderer·canvas·thumbs·splitter)을 생성하여 반환."""
        doc      = PdfDocument()
        # 저장 옵션(글꼴 서브셋 등)을 새 탭에도 그대로 적용
        doc.subset_fonts_enabled = bool(getattr(self._settings, 'subset_fonts', True))
        renderer = PageRenderer(doc)
        canvas   = PdfCanvasView(doc, renderer)
        canvas.set_settings(self._settings)
        thumbs   = ThumbnailPanel(doc, renderer)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(thumbs)
        splitter.addWidget(canvas)
        thumbs.hide()
        splitter.setSizes([0, 1000])
        return _DocTab(doc, renderer, canvas, thumbs, splitter)


    def _tab_signal_pairs(self, tab: '_DocTab'):
        """connect/disconnect 가 항상 같은 목록을 쓰도록 한 곳에서 정의."""
        return [
            (tab.doc.opened,                    self._on_doc_opened),
            (tab.doc.structure_changed,         self._on_structure_changed),
            (tab.doc.saved,                     self._on_doc_saved),
            (tab.canvas.page_changed,           self._on_page_changed),
            (tab.canvas.display_zoom_changed,   self._on_display_zoom_changed),
            (tab.canvas.pending_count_changed,  self._on_pending_count),
            (tab.canvas.annot_committed,        self._on_annot_committed),
            (tab.canvas.region_captured,        self._on_region_captured),
            (tab.canvas.status_message,         self._status_lbl.setText),
            (tab.canvas.context_menu_requested, self._show_canvas_context_menu),
            (tab.thumbs.page_selected,          self._on_thumbnail_page_selected),
        ]

    def _connect_tab_signals(self, tab: '_DocTab'):
        # 중복 연결 방지: 먼저 해제 후 연결
        self._disconnect_tab_signals(tab)
        for sig, slot in self._tab_signal_pairs(tab):
            sig.connect(slot)
        tab.signals_connected = True

    def _disconnect_tab_signals(self, tab: '_DocTab'):
        # 아직 연결한 적이 없으면 시도하지 않는다. PySide6 는 없는 연결을 끊으려
        # 하면 예외가 아니라 RuntimeWarning 을 찍어서 try/except 로 못 막고,
        # 탭을 열 때마다 콘솔에 경고가 쏟아졌다.
        if not tab.signals_connected:
            return
        for sig, slot in self._tab_signal_pairs(tab):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                swallowed()
        tab.signals_connected = False


    def _remove_tab_widget(self, idx: int):
        self._tab_widget.blockSignals(True)
        self._tab_widget.removeTab(idx)
        self._tab_widget.blockSignals(False)


    def _select_tab_after_close(self, closed_idx: int):
        if self._tab_widget.count() > 0:
            new_idx = max(0, min(closed_idx, self._tab_widget.count() - 1))
            self._tab_widget.blockSignals(True)
            self._tab_widget.setCurrentIndex(new_idx)
            self._tab_widget.blockSignals(False)
            self._on_tab_changed(new_idx)


    def _dispose_pdf_tab(self, tab: '_DocTab'):
        temp_path = tab.temp_path if tab.source == 'hwp_export' else ''
        if tab.doc.is_open:
            tab.doc.close()
        tab.renderer.close()
        tab.splitter.deleteLater()
        if temp_path:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                swallowed()


    def _prepare_pdf_tab_for_close(self, tab: '_DocTab'):
        try:
            tab.canvas._stop_scroll_worker()
        except Exception:
            swallowed()
        for name in (
            '_dict_timer',
            '_hq_timer',
            '_scroll_batch_timer',
            '_scroll_window_timer',
            '_hud_hide_timer',
        ):
            timer = getattr(tab.canvas, name, None)
            if timer is not None:
                timer.stop()


    def _new_tab(self, path: str | None = None, source: str = 'pdf', temp_path: str = ''):
        """새 탭을 생성하고 포커스를 이동한다."""
        # 위장 파일이면 탭 자체를 만들지 않는다 (source='pdf' = 실제 파일 열기)
        if path and source == 'pdf' and not self._security_gate(path):
            return
        tab = self._make_tab()
        tab.source = source
        tab.temp_path = temp_path
        self._tabs.append(tab)
        label = Path(path).name if path else '새 문서'
        idx = self._tab_widget.addTab(tab.splitter, label)
        self._attach_tab_close_btn(idx)
        # 시그널 연결은 _on_tab_changed 에서 처리 (setCurrentIndex 가 currentChanged 발화)
        self._tab_widget.setCurrentIndex(idx)
        if path:
            ext = Path(path).suffix.lower()
            if ext in getattr(self, '_IMAGE_EXTS', set()):
                tab.doc.open_image(path)
            elif not tab.doc.open(path) and tab.doc.needs_password:
                # 암호화 PDF — 열람 암호 입력받아 인증
                from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox
                for _ in range(3):
                    pw, ok = QInputDialog.getText(
                        self, '암호 필요',
                        f'암호로 보호된 PDF입니다. 열람 암호를 입력하세요:\n{Path(path).name}',
                        QLineEdit.EchoMode.Password)
                    if not ok:
                        break
                    if tab.doc.open(path, pw):
                        break
                    QMessageBox.warning(self, '암호 오류', '암호가 올바르지 않습니다.')


    def _close_tab(self, idx: int):
        """탭을 닫는다. 마지막 PDF 탭이면 문서만 닫고 탭은 유지."""

        if idx < 0 or idx >= self._tab_widget.count():
            return

        self._in_tab_close = True
        try:
            pdf_idx = idx

            if len(self._tabs) <= 1:
                # 마지막 PDF 탭: 문서만 닫고 탭은 유지
                tab = self._tabs[0]
                if tab.doc.is_open:
                    if not self._confirm_discard():
                        return
                    tab.doc.close()   # doc.closed → canvas가 화면을 즉시 비움
                    # 마지막 PDF 탭의 widget 인덱스를 찾아서 제목 변경
                    widget_idx = self._tab_widget.indexOf(tab.splitter)
                    if widget_idx >= 0:
                        self._tab_widget.setTabText(widget_idx, '새 문서')
                    self.setWindowTitle(_cfg.window_title())
                    if hasattr(self, '_status_lbl'):
                        self._status_lbl.setText(' ')
                    if hasattr(self, '_page_lbl'):
                        self._page_lbl.setText('')
                    if tab.thumbs.isVisible():
                        tab.thumbs.reload()
                return

            tab = self._tabs[pdf_idx]
            # 미저장 변경사항 확인
            if tab.doc.is_open:
                pending = tab.canvas.pending_layer().count()
                if tab.doc.dirty or pending > 0:
                    if idx == self._current_tab_idx:
                        if not self._confirm_discard():
                            return
                    else:
                        name = Path(tab.doc.path).name if tab.doc.path else '새 문서'
                        ans = QMessageBox.question(
                            self, '탭 닫기',
                            f'"{name}"에 저장되지 않은 변경사항이 있습니다.\n저장하지 않고 닫으시겠습니까?',
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No,
                        )
                        if ans != QMessageBox.StandardButton.Yes:
                            return

            self._prepare_pdf_tab_for_close(tab)
            self._disconnect_tab_signals(tab)
            self._remove_tab_widget(idx)
            self._tabs.pop(pdf_idx)
            self._dispose_pdf_tab(tab)
            self._select_tab_after_close(idx)
        finally:
            self._in_tab_close = False


    def _on_tab_changed(self, idx: int):
        """탭이 전환될 때 alias를 갱신하고 UI를 동기화한다."""
        if idx < 0:
            return

        # 어노테이션 툴바 복원
        if hasattr(self, '_annot_bar'):
            self._annot_bar.setVisible(True)
        if hasattr(self, '_view_toolbar'):
            self._view_toolbar.setVisible(True)
        if hasattr(self, '_doc_toolbar'):
            self._doc_toolbar.setVisible(True)

        pdf_idx = idx
        if pdf_idx < 0 or pdf_idx >= len(self._tabs):
            return

        # 이전 탭 시그널 해제
        prev_idx = self._current_tab_idx
        if prev_idx != idx:
            prev_pdf = prev_idx
            if 0 <= prev_pdf < len(self._tabs):
                self._disconnect_tab_signals(self._tabs[prev_pdf])

        self._current_tab_idx = idx
        tab = self._tabs[pdf_idx]

        # ── 새 탭 시그널 연결 ────────────────────────────────────────
        self._connect_tab_signals(tab)

        # ── alias 갱신 ────────────────────────────────────────────
        self._doc      = tab.doc
        self._renderer = tab.renderer
        self._canvas   = tab.canvas
        self._thumbs   = tab.thumbs
        self._splitter = tab.splitter
        if hasattr(self, '_thumbnail_toggle_action'):
            self._thumbnail_toggle_action.blockSignals(True)
            self._thumbnail_toggle_action.setChecked(tab.thumbs.isVisible())
            self._thumbnail_toggle_action.blockSignals(False)

        # 어노테이션 툴바를 새 캔버스에 연결
        if hasattr(self, '_annot_bar'):
            self._annot_bar.set_canvas(tab.canvas)

        # 확대율 라벨을 새 탭 기준으로 갱신
        self._on_display_zoom_changed(tab.canvas.display_zoom())

        # OCR 패널도 현재 탭 문서·캔버스로 갱신
        ocr = getattr(self, '_ocr_panel', None)
        if ocr is not None:
            ocr._doc    = tab.doc
            ocr._canvas = tab.canvas

        # ── UI 상태 동기화 ────────────────────────────────────────
        if tab.doc.is_open:
            name = Path(tab.doc.path).name if tab.doc.path else ''
            self.setWindowTitle(_cfg.window_title(name))
            n = tab.doc.page_count()
            if hasattr(self, '_page_spin'):
                self._page_spin.setMaximum(max(1, n))
                self._page_spin.setValue(tab.canvas.current_page() + 1)
            self._page_lbl.setText(f'{tab.canvas.current_page() + 1} / {n}')
            pending = tab.canvas.pending_layer().count()
            self._on_pending_count(pending)
        else:
            self.setWindowTitle(_cfg.window_title())
            if hasattr(self, '_page_spin'):
                self._page_spin.setMaximum(1)
                self._page_spin.setValue(1)
            self._page_lbl.setText('')
            self._on_pending_count(0)


    def _update_current_tab_title(self):
        """현재 탭의 제목을 문서 파일명으로 갱신한다."""
        idx = self._tab_widget.currentIndex()
        if idx < 0:
            return
        pdf_idx = idx
        if pdf_idx >= len(self._tabs):
            return
        doc = self._tabs[pdf_idx].doc
        if doc.is_open and doc.path:
            title = Path(doc.path).name
        else:
            title = '새 문서'
        self._tab_widget.setTabText(idx, title)


    def _toggle_tab_bar(self):
        """탭 바를 켜거나 끈다."""
        visible = not self._tab_widget.tabBar().isVisible()
        self._tab_widget.tabBar().setVisible(visible)
        self._new_tab_btn.setVisible(visible)
        self._settings.tabs_enabled = visible
        self._settings.save()
        if hasattr(self, '_tab_toggle_action'):
            self._tab_toggle_action.setChecked(visible)

