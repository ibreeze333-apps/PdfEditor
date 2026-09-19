# ui/mainwin/snapshot.py — MainWindow 스냅샷 캡처와 클립보드 처리 믹스인
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


class SnapshotMixin:
    """MainWindow 스냅샷 캡처와 클립보드 처리."""



    def _copy_permission_ok(self, what: str) -> bool:
        """복사 권한이 없는 문서에서 화면 캡처를 막는다.

        스냅샷·영역 캡처는 결국 문서 내용을 그림으로 빼내는 것이라,
        복사 금지 문서에서는 허용하면 권한 제한이 무의미해진다.
        """
        if getattr(self, '_perm_copy_ok', True):
            return True
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            self, what,
            '이 문서는 복사가 제한되어 있어 화면 캡처를 할 수 없습니다.\n'
            '관리자 암호로 열면 사용할 수 있습니다.')
        self._status_lbl.setText(f'🔒 복사 제한 문서 — {what} 불가')
        return False

    def _do_snapshot(self):
        """📷 찍기 버튼 — PDF 캔버스 캡처 → 스냅샷 창에 저장 후 자동 표시."""
        if not self._doc.is_open:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, '스냅샷', 'PDF 파일을 먼저 열어주세요.')
            return
        if not self._copy_permission_ok('스냅샷'):
            return
        self._snapshot()
        # 스냅샷 창이 닫혀 있으면 열기
        if not self._clip_dock.isVisible():
            self._clip_dock.show()
            self._clip_dock.raise_()
        # 스냅샷 탭으로 전환
        self._clipboard_panel.show_snapshots()


    def _snapshot(self):
        """현재 화면을 PNG 스냅샷으로 저장하고 복사한다."""
        if not self._doc.is_open:
            return
        if not getattr(self, '_perm_copy_ok', True):
            self._status_lbl.setText('🔒 복사 제한 문서 — 스냅샷 불가')
            return
        px = self._canvas.grab()
        self._clipboard_panel.add_snapshot(px)
        if getattr(self, '_perm_copy_ok', True):
            self._clipboard_guard = True
            QApplication.clipboard().setPixmap(px)
            self._clipboard_guard = False
            self._status_lbl.setText('스냅샷 저장 완료 — 스냅샷 창에서 항목을 더블클릭하면 클립보드로 복사됩니다.')
        else:
            self._status_lbl.setText('🔒 이 문서는 복사가 제한되어 클립보드 복사를 건너뜁니다 (스냅샷 창에는 저장됨).')


    # ── 영역 캡처 ───────────────────────────────────────────────────
    def _start_region_capture(self):
        """영역 선택 캡처 모드 진입."""
        if not self._doc.is_open:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, '영역 캡처', 'PDF 파일을 먼저 열어주세요.')
            return
        if not self._copy_permission_ok('영역 캡처'):
            return
        self._canvas.start_region_capture()
        self._status_lbl.setText(
            '✂ 영역 캡처: 캔버스 위에서 드래그로 원하는 영역을 선택하세요.')
        # 스냅샷 창이 닫혀 있으면 열기
        if not self._clip_dock.isVisible():
            self._clip_dock.show()
            self._clip_dock.raise_()
        self._clipboard_panel.show_snapshots()


    def _on_region_captured(self, px: 'QPixmap'):
        """영역 캡처 완료 시 스냅샷에 추가."""
        self._clipboard_panel.add_snapshot(px)
        if not getattr(self, '_perm_copy_ok', True):
            self._status_lbl.setText('🔒 복사 제한 문서 — 클립보드 복사를 건너뜁니다 (스냅샷 창에는 저장됨).')
            return
        self._clipboard_guard = True
        QApplication.clipboard().setPixmap(px)
        self._clipboard_guard = False
        self._status_lbl.setText(
            f'영역 캡처 완료 ({px.width()}×{px.height()}) — '
            '스냅샷 창에서 항목을 더블클릭하면 클립보드로 복사됩니다.')


    # ── 스냅샷 파일 저장 ────────────────────────────────────────────
    def _save_snapshot_to_file(self, px: 'QPixmap'):
        """스냅샷을 PNG/JPG 파일로 저장."""
        from PySide6.QtWidgets import QFileDialog
        path, selected_filter = QFileDialog.getSaveFileName(
            self, '스냅샷 저장', '',
            'PNG 이미지 (*.png);;JPEG 이미지 (*.jpg *.jpeg);;모든 파일 (*)')
        if not path:
            return
        # 확장자가 없으면 PNG 기본
        import os
        ext = os.path.splitext(path)[1].lower()
        if not ext:
            path += '.png'
            ext = '.png'
        fmt = 'JPEG' if ext in ('.jpg', '.jpeg') else 'PNG'
        quality = 92 if fmt == 'JPEG' else -1
        if px.save(path, fmt, quality):
            self._status_lbl.setText(f'스냅샷 저장 완료: {path}')
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, '저장 실패', f'파일을 저장할 수 없습니다:\n{path}')


    # ── 스냅샷 → PDF 삽입 ──────────────────────────────────────────
    def _insert_snapshot_to_pdf(self, px: 'QPixmap'):
        """스냅샷을 현재 PDF 페이지 중앙에 이미지 어노테이션으로 삽입."""
        import os, tempfile
        import fitz
        from utils.pending_layer import PendingAnnotation

        if not self._doc.is_open:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, 'PDF 삽입', 'PDF 파일을 먼저 열어주세요.')
            return

        # QPixmap → 임시 PNG 파일
        fd, tmp_path = tempfile.mkstemp(suffix='.png', prefix='snap_')
        os.close(fd)
        if not px.save(tmp_path, 'PNG'):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'PDF 삽입', '이미지 변환에 실패했습니다.')
            return
        self._snapshot_tmp_files.append(tmp_path)

        # 현재 페이지 크기(PDF point)에서 60% 크기 사각형을 중앙에 배치
        cur = self._canvas.current_page()
        page = self._doc.fitz_doc().load_page(cur)
        pw, ph = page.rect.width, page.rect.height

        # 이미지 비율 유지하여 최대 60% 영역에 맞춤
        img_ratio = px.width() / max(1, px.height())
        target_w = pw * 0.60
        target_h = target_w / img_ratio
        if target_h > ph * 0.60:
            target_h = ph * 0.60
            target_w = target_h * img_ratio

        x0 = (pw - target_w) / 2.0
        y0 = (ph - target_h) / 2.0
        frect = fitz.Rect(x0, y0, x0 + target_w, y0 + target_h)

        uid = self._canvas.pending_layer().next_uid()
        pa = PendingAnnotation(
            uid=uid,
            page_index=cur,
            tool_name='snapshot',
            annot_type='image',
            fitz_rect=frect,
            image_path=tmp_path,
        )
        self._canvas.pending_layer().add(pa)
        self._canvas.refresh_page()
        self._canvas.notify_pending_changed()
        self._status_lbl.setText(
            f'스냅샷이 페이지 {cur + 1}에 삽입됐습니다. '
            '"변경사항 PDF에 적용"으로 저장하세요.')


    # ── 스냅샷 비교 ─────────────────────────────────────────────────
    def _open_snapshot_compare(self, snapshots: list):
        """스냅샷 비교 다이얼로그 열기."""
        from ui.dialogs.snapshot_compare_dialog import SnapshotCompareDialog
        dlg = SnapshotCompareDialog(snapshots, self)
        dlg.exec()


    def _on_clipboard_changed(self):
        if self._clipboard_guard:
            return
        cb = QApplication.clipboard()
        mime = cb.mimeData()
        if mime is None:
            return
        if mime.hasImage():
            px = cb.pixmap()
            if not px.isNull():
                self._clipboard_panel.add_clipboard_image(px)
                return
        if mime.hasText():
            self._clipboard_panel.add_clipboard_text(cb.text())


    def _restore_clipboard_text(self, text: str):
        self._clipboard_guard = True
        QApplication.clipboard().setText(text, QClipboard.Mode.Clipboard)
        self._clipboard_guard = False
        self._status_lbl.setText('클립보드 텍스트를 복원했습니다.')

    def _restore_clipboard_image(self, pixmap: QPixmap):
        if pixmap.isNull():
            return
        self._clipboard_guard = True
        QApplication.clipboard().setPixmap(pixmap, QClipboard.Mode.Clipboard)
        self._clipboard_guard = False
        self._status_lbl.setText('클립보드 이미지를 복원했습니다.')

