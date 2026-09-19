# ui/mainwin/page_ops.py — MainWindow 페이지 삽입/삭제/회전/자르기/분할/병합/워터마크 믹스인
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


class PageOpsMixin:
    """MainWindow 페이지 삽입/삭제/회전/자르기/분할/병합/워터마크."""


    # ── 페이지 동작 ──────────────────────────────────────────────────
    def _insert_blank(self):
        if not self._doc.is_open:
            return
        self._doc.insert_blank_page(self._canvas.current_page() + 1)


    def _insert_img_page(self):
        if not self._doc.is_open:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, '이미지 선택', '',
            '이미지 (*.png *.jpg *.jpeg *.bmp *.webp *.tiff)')
        if path:
            self._doc.insert_image_as_page(
                self._canvas.current_page() + 1, path)


    def _delete_page(self):
        if not self._doc.is_open or self._doc.page_count() <= 1:
            return
        idx = self._canvas.current_page()
        if QMessageBox.question(
                self, '페이지 삭제',
                f'페이지 {idx + 1}을 삭제하시겠습니까?',
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No)                 == QMessageBox.StandardButton.Yes:
            self._doc.delete_page(idx)


    def _crop_page(self):
        if not self._doc.is_open:
            return
        from ui.dialogs.crop_dialog import CropDialog
        idx  = self._canvas.current_page()
        page = self._doc.fitz_page(idx)
        dlg  = CropDialog(page, zoom=self._canvas.zoom(), parent=self)
        if dlg.exec() and dlg.crop_rect():
            self._doc.crop_page(idx, dlg.crop_rect())
            self._canvas.refresh_page()


    def _rotate_cw(self):
        self._rotate_with_range(90, '시계 방향 회전')


    def _rotate_ccw(self):
        self._rotate_with_range(-90, '반시계 방향 회전')


    def _rotate_with_range(self, degrees: int, title: str):
        """회전할 범위(현재 페이지 / 지정 / 전체)를 물어보고 회전한다."""
        if not self._doc.is_open:
            return
        from ui.dialogs.rotate_dialog import RotateDialog
        cur = self._canvas.current_page()
        dlg = RotateDialog(self, title=title,
                           page_count=self._doc.page_count(), current_page=cur)
        if not dlg.exec():
            return
        pages = dlg.pages()
        if not pages:
            return
        n = self._doc.rotate_pages(pages, degrees)
        if not n:
            return
        # 회전한 페이지만 렌더 캐시를 비운다(전체면 한 번에)
        if n >= self._doc.page_count():
            self._renderer.invalidate_all()
        else:
            for p in pages:
                self._renderer.invalidate(p)
        self._canvas.refresh_page()
        if hasattr(self, '_status_lbl'):
            where = ('문서 전체' if n >= self._doc.page_count()
                     else (f'{pages[0] + 1}쪽' if n == 1 else f'{n}쪽'))
            self._status_lbl.setText(f'{title}: {where} 완료')


    def _split_pdf(self):
        if not self._doc.is_open:
            return
        from ui.dialogs.split_pdf_dialog import SplitPdfDialog
        dlg = SplitPdfDialog(self._doc.page_count(), self)
        if dlg.exec():
            dlg.split(self._doc.fitz_doc())


    def _merge_pdf(self):
        from ui.dialogs.merge_pdf_dialog import MergePdfDialog
        MergePdfDialog(self).exec()


    # ── 구성 ─────────────────────────────────────────────────────────
    def _add_watermark(self):
        if not self._doc.is_open:
            return
        from ui.dialogs.watermark_dialog import WatermarkDialog
        dlg = WatermarkDialog(self)
        if dlg.exec():
            fitz_doc = self._doc.fitz_doc()
            pages = (list(range(fitz_doc.page_count))
                     if dlg.all_pages() else [self._canvas.current_page()])
            if dlg.mode() == 'image':
                if not dlg.image_path():
                    QMessageBox.warning(self, '오류', '이미지 파일을 먼저 선택하세요.')
                    return
                WatermarkDialog.apply_image(
                    fitz_doc, dlg.image_path(), dlg.image_scale(), dlg.angle(), pages)
            else:
                WatermarkDialog.apply_text(
                    fitz_doc, dlg.text(), dlg.font_size(),
                    dlg.opacity(), dlg.angle(), dlg.color(), pages)
            self._renderer.invalidate_all()
            self._canvas.refresh_page()
            self._status_lbl.setText('워터마크 추가 완료')


    def _header_footer(self):
        if not self._doc.is_open:
            return
        from ui.dialogs.header_footer_dialog import HeaderFooterDialog
        dlg = HeaderFooterDialog(self)
        if dlg.exec():
            HeaderFooterDialog.apply(
                self._doc.fitz_doc(),
                dlg.header_text(), dlg.footer_text(),
                dlg.hdr_margin(), dlg.ftr_margin(), dlg.font_size())
            self._renderer.invalidate_all()
            self._canvas.refresh_page()
            self._status_lbl.setText('머리글/바닥글 적용 완료')

