# ui/mainwin/autosave.py — MainWindow 자동 저장/복구/비상 저장 믹스인
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

# 자동 저장 경로 (프로젝트 루트/autosave/)
_AUTOSAVE_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'autosave')
_AUTOSAVE_PDF  = os.path.join(_AUTOSAVE_DIR, 'autosave.pdf')
_AUTOSAVE_META = os.path.join(_AUTOSAVE_DIR, 'autosave.meta')


class AutosaveMixin:
    """MainWindow 자동 저장/복구/비상 저장."""



    def _auto_save(self):
        if self._text_draft_active:
            return
        if not self._doc.is_open or not self._doc.dirty:
            return
        # 직전 자동저장이 느렸다면(대용량 문서) 몇 틱 건너뛴다 —
        # GUI 스레드에서 돌기 때문에 매 틱 멈추면 사용이 불가능해진다
        skip = getattr(self, '_autosave_skip_ticks', 0)
        if skip > 0:
            self._autosave_skip_ticks = skip - 1
            return
        # 열람 암호로만 연 제한 문서는 자동저장하지 않는다 — 자동저장 폴더에
        # 암호가 풀린 사본이 남으면 권한 제한을 우회할 수 있다.
        if not getattr(self._doc, 'opened_as_owner', True):
            return
        try:
            import time as _time
            os.makedirs(_AUTOSAVE_DIR, exist_ok=True)
            _t0 = _time.perf_counter()
            # 복구용이므로 압축/정리 생략 (garbage=0: 1200페이지도 ~20ms)
            self._doc.save_copy(_AUTOSAVE_PDF, garbage=0, deflate=False)
            _dur = _time.perf_counter() - _t0
            # 1초 넘게 걸리면 다음 몇 틱을 건너뛰어 체감 멈춤 방지
            if _dur > 1.0:
                self._autosave_skip_ticks = min(9, int(_dur))
                import logging
                logging.getLogger('pdf_editor').info(
                    '[AutoSave] %.1fs 소요 — 다음 %d틱 건너뜀',
                    _dur, self._autosave_skip_ticks)
            with open(_AUTOSAVE_META, 'w', encoding='utf-8') as f:
                f.write(self._doc.path or '')
            self._status_lbl.setText(f'자동 저장: {_AUTOSAVE_PDF}')
            QTimer.singleShot(3000, lambda: (
                self._status_lbl.setText(
                    f': {self._doc.path}' if self._doc.path else ' ')
                if self._doc.is_open and not self._text_draft_active else None))
        except Exception as e:
            print(f'[AutoSave] error: {e}')

    def _clear_autosave(self):
        for p in (_AUTOSAVE_PDF, _AUTOSAVE_META):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                swallowed()


    def _check_recovery(self):
        if self._text_draft_active:
            return
        if not os.path.exists(_AUTOSAVE_PDF):
            return
        orig_path = ''
        try:
            if os.path.exists(_AUTOSAVE_META):
                with open(_AUTOSAVE_META, 'r', encoding='utf-8') as f:
                    orig_path = f.read().strip()
        except Exception:
            swallowed()
        import time
        mtime = os.path.getmtime(_AUTOSAVE_PDF)
        time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
        detail = f'저장 시각: {time_str}'
        if orig_path:
            detail += f'\n원본 파일: {orig_path}'
        ans = QMessageBox.question(
            self, '자동 저장 파일 발견',
            f'이전 작업의 자동 저장 파일이 있습니다.\n{detail}\n\n복구하시겠습니까?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ans == QMessageBox.StandardButton.Yes:
            if self._doc.open(_AUTOSAVE_PDF):
                self._status_lbl.setText(
                    f'자동 저장 파일로 복구됨  - 원본: {orig_path or "(없음)"}')
            else:
                QMessageBox.critical(self, '복구 오류', f'자동 저장 파일을 열 수 없습니다.\n{_AUTOSAVE_PDF}')
        else:
            self._clear_autosave()


    def _emergency_save(self):
        if self._text_draft_active:
            return
        if not self._doc.is_open:
            return
        if not getattr(self._doc, 'opened_as_owner', True):
            return   # 위와 같은 이유 (암호 풀린 사본 방지)
        try:
            os.makedirs(_AUTOSAVE_DIR, exist_ok=True)
            self._doc.save_copy(_AUTOSAVE_PDF)
            with open(_AUTOSAVE_META, 'w', encoding='utf-8') as f:
                f.write(self._doc.path or '')
            print(f'[EmergencySave] saved: {_AUTOSAVE_PDF}')
        except Exception as e:
            print(f'[EmergencySave] error: {e}')

