# ui/mainwin/panels.py — MainWindow OCR/스냅샷/클립보드/메모/사전/Ollama 패널 믹스인
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


class PanelsMixin:
    """MainWindow OCR/스냅샷/클립보드/메모/사전/Ollama 패널."""


    def _ensure_ocr_panel(self, resize: bool = True):
        if self._ocr_panel is not None:
            return self._ocr_panel
        from ui.ocr_panel import OcrPanel
        panel = OcrPanel(self._doc, self._canvas, self._settings, self)
        self._ocr_panel = panel
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, panel)
        panel.setVisible(False)
        panel.visibilityChanged.connect(self._on_ocr_visibility_changed)
        self._install_large_dock_titlebars()
        if resize:
            self.resizeDocks([panel], [500], Qt.Orientation.Horizontal)
        return panel


    def _prewarm_ocr_panel(self):
        """앱 시작 직후 OCR 패널을 미리 생성해 둔다 (숨김 상태).

        resizeDocks 를 건너뛰어 레이아웃 재계산에 의한 화면 버벅임을 방지한다.
        실제 패널 크기 조정은 처음 열릴 때 수행된다.
        """
        try:
            self._ensure_ocr_panel(resize=False)
        except Exception:
            pass  # 실패해도 무시 — 클릭 시 재시도


    def _open_ollama_window(self):
        """Ollama 분석 창을 싱글톤으로 열고 앞으로 가져온다."""
        from ui.ollama_panel import OllamaAnalysisWindow
        if self._ollama_window is None:
            self._ollama_window = OllamaAnalysisWindow(
                self._settings,
                page_callbacks=self._make_translate_page_callbacks(),
                parent=None,
            )
        self._ollama_window.show()
        self._ollama_window.raise_()
        self._ollama_window.activateWindow()
        if hasattr(self, '_ollama_btn'):
            self._sync_window_button(self._ollama_btn, self._ollama_window)


    def _open_translate_hub(self):
        """번역 허브 창 (싱글톤) — Ollama·API·웹 AI 번역."""
        from ui.translate_hub import TranslateHubWindow
        win = getattr(self, '_translate_hub_win', None)
        if win is None:
            win = TranslateHubWindow(
                self._settings,
                page_callbacks=self._make_translate_page_callbacks(),
            )
            self._translate_hub_win = win
        else:
            # 탭 전환 등으로 문서가 바뀌었을 수 있으므로 콜백 갱신
            win._page_callbacks = self._make_translate_page_callbacks()
        win.show()
        win.raise_()
        win.activateWindow()
        if hasattr(self, '_translate_btn'):
            self._sync_window_button(self._translate_btn, win)

    def _open_ai_provider_settings(self):
        """AI 제공자(API 키) 설정 다이얼로그 — 번역 허브 없이도 접근 가능."""
        from ui.dialogs.ai_provider_dialog import AiProviderDialog
        dlg = AiProviderDialog(self._settings.ai_providers, self)
        if dlg.exec():
            self._settings.ai_providers = dlg.providers()
            self._settings.save()
            win = getattr(self, '_translate_hub_win', None)
            if win is not None:
                win._reload_providers()

    def _make_translate_page_callbacks(self) -> dict:
        """번역창에 넘길 콜백 모음."""

        def is_open():
            return self._doc.is_open

        def page_count():
            return self._doc.page_count() if self._doc.is_open else 0

        def current_page():
            return self._canvas.current_page()

        def get_page_data(pages: list[int]):
            """메인 스레드에서 호출 — fitz 안전, 텍스트 추출 or 이미지 렌더링.

            OCR 패널 fast 모드와 동일한 extract_page_text() 를 사용하므로
            '페이지 번역'과 'OCR 뽑기 → 번역' 결과가 일치한다.
            """
            from utils.fitz_qt_bridge import render_page, extract_page_text
            from workers.ocr_worker import qimage_to_np
            result = []
            for idx in pages:
                try:
                    page = self._doc.fitz_page(idx)
                    text = extract_page_text(page)
                    if text:
                        result.append((idx, text))
                    else:
                        # 스캔 PDF → OCR 렌더링
                        img = render_page(page, zoom=2.0)
                        result.append((idx, qimage_to_np(img)))
                except Exception:
                    swallowed()
            return result

        return {
            'is_open': is_open,
            'page_count': page_count,
            'current_page': current_page,
            'get_page_data': get_page_data,
        }



    def _toggle_snapshot_panel(self):
        """스냅샷/클립보드 패널 열기·닫기 (토글)."""
        visible = not self._clip_dock.isVisible()
        self._clip_dock.setVisible(visible)
        if visible:
            self._clip_dock.raise_()
        if hasattr(self, '_clip_corner_btn'):
            self._clip_corner_btn.setChecked(visible)


    def _toggle_ocr(self):
        panel = self._ocr_panel
        visible = panel is None or not panel.isVisible()
        if visible:
            self._ocr_restore_geometry = self.saveGeometry()
            self._ocr_restore_splitter = self._splitter
            self._ocr_restore_splitter_sizes = self._splitter.sizes()
            self._ocr_restore_maximized = self.isMaximized()
        panel = self._ensure_ocr_panel()
        panel.setVisible(visible)
        if visible:
            panel.raise_()
        if hasattr(self, '_ocr_corner_btn'):
            self._ocr_corner_btn.setChecked(visible)


    def _on_ocr_visibility_changed(self, visible: bool):
        if hasattr(self, '_ocr_corner_btn'):
            self._ocr_corner_btn.setChecked(visible)
        if not visible and self._ocr_restore_geometry is not None:
            QTimer.singleShot(0, self._restore_after_ocr_close)


    def _restore_after_ocr_close(self):
        geometry = self._ocr_restore_geometry
        splitter = self._ocr_restore_splitter
        splitter_sizes = self._ocr_restore_splitter_sizes
        was_maximized = self._ocr_restore_maximized
        self._ocr_restore_geometry = None
        self._ocr_restore_splitter = None
        self._ocr_restore_splitter_sizes = None
        self._ocr_restore_maximized = False
        if geometry is not None and not was_maximized:
            self.restoreGeometry(geometry)
        if splitter is not None and splitter_sizes:
            try:
                splitter.setSizes(splitter_sizes)
            except RuntimeError:
                swallowed()
        if hasattr(self, '_doc_toolbar'):
            self._doc_toolbar.updateGeometry()


    def _toggle_thumbnail_panel(self, checked: bool):
        if checked:
            self._thumbs.show()
            total = max(181, sum(self._splitter.sizes()))
            self._splitter.setSizes([180, total - 180])
            if self._doc.is_open:
                self._thumbs.reload()
        else:
            self._thumbs.hide()
            self._splitter.setSizes([0, 1])

    def _install_large_dock_titlebars(self):
        docks = [dock for dock in [getattr(self, '_ocr_panel', None), getattr(self, '_clip_dock', None), getattr(self, '_note_dock', None)] if dock is not None]
        for dock in docks:
            if dock.titleBarWidget() is not None:   # 이미 설치됨 → 건너뜀
                continue
            title = dock.windowTitle() or ''
            bar = QWidget(dock)
            layout = QHBoxLayout(bar)
            layout.setContentsMargins(10, 4, 4, 4)
            layout.setSpacing(4)

            label = QLabel(title, bar)
            label.setStyleSheet('font-weight: bold; font-size: 13px; color: #1e2532;')
            layout.addWidget(label)
            layout.addStretch(1)

            _dock_btn_style = (
                'QPushButton { font-size: 14px; font-weight: bold; color: #4b5563;'
                '  border: 1px solid #d1d5db; border-radius: 5px;'
                '  background: #ffffff; padding: 0px; }'
                'QPushButton:hover { background: #e5e7eb; color: #1e2532; border-color: #9ca3af; }'
                'QPushButton:pressed { background: #d1d5db; }'
            )
            _close_btn_style = (
                'QPushButton { font-size: 14px; font-weight: bold; color: #6b7280;'
                '  border: 1px solid #d1d5db; border-radius: 5px;'
                '  background: #ffffff; padding: 0px; }'
                'QPushButton:hover { background: #fee2e2; color: #dc2626; border-color: #fca5a5; }'
                'QPushButton:pressed { background: #fecaca; }'
            )

            float_btn = QPushButton('⧉', bar)
            float_btn.setToolTip('분리 / 도킹')
            float_btn.setFixedSize(28, 26)
            float_btn.setStyleSheet(_dock_btn_style)
            float_btn.clicked.connect(lambda checked=False, d=dock: d.setFloating(not d.isFloating()))
            layout.addWidget(float_btn)

            close_btn = QPushButton('✕', bar)
            close_btn.setToolTip('닫기')
            close_btn.setFixedSize(28, 26)
            close_btn.setStyleSheet(_close_btn_style)
            close_btn.clicked.connect(dock.hide)
            layout.addWidget(close_btn)

            bar.setStyleSheet('QWidget { background: #f0f2f5; border-bottom: 1px solid #e0e3e8; }')
            dock.setTitleBarWidget(bar)


    def _show_snapshot_panel(self):
        self._toggle_snapshot_panel()
        self._clipboard_panel.show_snapshots()


    def _show_clipboard_panel(self):
        self._clip_dock.show()
        self._clip_dock.raise_()
        self._clipboard_panel.show_clipboard()


    def _toggle_clipboard_panel(self):
        visible = not self._clip_dock.isVisible()
        self._clip_dock.setVisible(visible)
        if visible:
            self._clip_dock.raise_()
            self._clipboard_panel.show_snapshots()

    def _show_note_panel(self):
        if self._note_dock.isVisible():
            self._note_dock.hide()
            return
        self._refresh_note_panel()
        self._note_dock.show()
        self._note_dock.raise_()


    def _collect_note_entries(self):
        entries = []
        if self._doc.is_open:
            for page_idx in range(self._doc.page_count()):
                try:
                    page = self._doc.fitz_page(page_idx)
                    annots = page.annots()
                    if annots is not None:
                        for annot in annots:
                            try:
                                atype = annot.type[1] if isinstance(annot.type, tuple) else str(annot.type)
                                if str(atype).lower() != 'text':
                                    continue
                                info = annot.info or {}
                                memo_text = (info.get('content') or info.get('subject') or info.get('title') or '').strip()
                                if not memo_text:
                                    memo_text = '(empty memo)'
                                entries.append({
                                    'page_index': page_idx,
                                    'text': memo_text,
                                    'source': 'saved',
                                    'xref': getattr(annot, 'xref', 0),
                                })
                            except Exception:
                                continue
                except Exception:
                    continue

        for pa in self._canvas.pending_layer().all():
            if getattr(pa, 'tool_name', '') != 'note':
                continue
            entries.append({
                'page_index': pa.page_index,
                'text': (pa.text or '').strip() or '(empty memo)',
                'source': 'pending',
                'uid': pa.uid,
            })

        entries.sort(key=lambda e: (e.get('page_index', 0), 0 if e.get('source') == 'pending' else 1, (e.get('text') or '').lower()))
        return entries


    def _refresh_note_panel(self):
        self._note_panel.set_notes(self._collect_note_entries())


    def _open_note_entry(self, page_index: int):
        if not self._doc.is_open:
            return
        if self._reflow_active:
            self._reflow_view.go_to_page(page_index)
        else:
            view_mode = getattr(self, '_view_mode', UI.VIEW_SINGLE)
            if view_mode == UI.VIEW_SEGMENT:
                self._canvas.show_segment(page_index, 0, 2)
            else:
                self._canvas.show_page(page_index)
        self._status_lbl.setText(f'메모가 있는 {page_index + 1}페이지로 이동했습니다.')


    def _open_dict_window(self, word: str = ''):
        """사전 창을 싱글톤으로 열고 word를 검색."""
        from ui.dict_window import DictWindow
        if self._dict_window is None:
            self._dict_window = DictWindow(settings=self._settings, parent=None)
        if word:
            self._dict_window.lookup(word)
        else:
            self._dict_window.show()
            self._dict_window.raise_()
            self._dict_window.activateWindow()
        if hasattr(self, '_dict_btn'):
            self._sync_window_button(self._dict_btn, self._dict_window)


    def _apply_dict_settings(self):
        """저장된 사전 설정 적용 (시작 시 자동 로드).

        StarDict 파싱은 수십만 항목 기준 ~2초가 걸리므로 백그라운드
        스레드에서 로드한다 — 시작 직후 사전 조회는 로드 완료 전까지
        조용히 None을 반환한다 (load_many가 마지막에 원자적으로 할당).
        """
        from utils.dict_manager import dict_manager
        dm = dict_manager()
        online_mode = getattr(self._settings, 'dict_online_mode', False)
        # 온라인 모드일 때는 로컬 파일 없이도 hover 감지가 동작해야 하므로 enabled = True
        dm.enabled = self._settings.dict_enabled or online_mode
        if self._settings.dict_path and self._settings.dict_enabled and not online_mode:
            # 파일 존재 검사는 GUI 스레드에서 즉시 (설정 정리도 여기서)
            if not os.path.exists(self._settings.dict_path):
                self._settings.dict_path = ''
                self._settings.save()
                return
            import threading
            dict_path = self._settings.dict_path

            def _load_in_background():
                import logging
                try:
                    ok, msg = dm.load(dict_path)
                    if not ok:
                        logging.getLogger('pdf_editor').warning(
                            '사전 로드 실패: %s', msg)
                except Exception:
                    logging.getLogger('pdf_editor').exception('사전 로드 오류')

            # 창이 표시된 뒤에 시작 — 파싱 스레드가 GIL을 잡고 있으면
            # 초기 UI 구성이 함께 느려진다
            QTimer.singleShot(1500, lambda: threading.Thread(
                target=_load_in_background,
                name='dict-loader', daemon=True).start())

