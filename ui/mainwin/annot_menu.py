# ui/mainwin/annot_menu.py — MainWindow 캔버스 컨텍스트 메뉴와 어노테이션 삭제/플래튼 믹스인
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


class AnnotMenuMixin:
    """MainWindow 캔버스 컨텍스트 메뉴와 어노테이션 삭제/플래튼."""


    def _show_canvas_context_menu(self, scene_pos, global_pos):
        from PySide6.QtWidgets import QMenu
        from utils.annot_mapper import scene_to_fitz_pt

        menu = QMenu(self)
        page_idx = self._canvas.current_page()
        hit_pending = None
        hit_xref = None

        if self._doc.is_open:
            fitz_pt = scene_to_fitz_pt(scene_pos, self._canvas.zoom())
            page = self._doc.fitz_page(page_idx)
            tol = 8.0

            for pa in self._canvas.pending_layer().all():
                if pa.page_index != page_idx:
                    continue
                rect = pa.bounding_fitz_rect()
                if rect is None:
                    continue
                if rect.x0 - tol <= fitz_pt.x <= rect.x1 + tol and rect.y0 - tol <= fitz_pt.y <= rect.y1 + tol:
                    hit_pending = pa
                    break

            if hit_pending is None:
                annots = page.annots()
                if annots is not None:
                    for annot in annots:
                        try:
                            rect = annot.rect
                            if rect.x0 - tol <= fitz_pt.x <= rect.x1 + tol and rect.y0 - tol <= fitz_pt.y <= rect.y1 + tol:
                                hit_xref = annot.xref
                                break
                        except Exception:
                            continue

            if hit_pending is not None:
                del_act = menu.addAction('🗑 어노테이션 삭제')
                del_act.triggered.connect(
                    lambda checked=False, _pa=hit_pending: self._delete_pending_annot(_pa))
                flat_act = menu.addAction('▣ 개별 플래튼')
                flat_act.triggered.connect(
                    lambda checked=False, _pa=hit_pending: self._flatten_pending_annot(_pa))
                menu.addSeparator()
            elif hit_xref is not None:
                del_act = menu.addAction('🗑 어노테이션 삭제')
                del_act.triggered.connect(
                    lambda checked=False, _idx=page_idx, _xref=hit_xref: self._delete_committed_annot(_idx, _xref))
                flat_act = menu.addAction('▣ 개별 플래튼')
                flat_act.triggered.connect(
                    lambda checked=False, _idx=page_idx, _xref=hit_xref: self._flatten_committed_annot(_idx, _xref))
                menu.addSeparator()

            word = self._canvas.selected_text_for_dict() or self._canvas.word_at_scene(scene_pos)
            if word:
                dict_act = menu.addAction(UI.CTX_DICT.format(word=word))
                dict_act.triggered.connect(
                    lambda checked=False, w=word: self._open_dict_window(w))
                menu.addSeparator()

            for label, tool in self._annot_bar.tool_items():
                act = menu.addAction(label)
                act.setCheckable(True)
                act.setChecked(self._canvas.current_tool() is tool)
                act.triggered.connect(
                    lambda checked=False, t=tool: self._ctx_toggle_tool(t))
        else:
            for label, tool in self._annot_bar.tool_items():
                act = menu.addAction(label)
                act.setCheckable(True)
                act.setChecked(self._canvas.current_tool() is tool)
                act.triggered.connect(
                    lambda checked=False, t=tool: self._ctx_toggle_tool(t))

        menu.addSeparator()
        menu.addAction(UI.ACT_FIT_PAGE, self._canvas.fit_page)
        menu.addAction(UI.ACT_FIT_WIDTH, self._canvas.fit_width)
        menu.addAction('100%', lambda: self._canvas.set_zoom(1.0))

        menu.addSeparator()
        book_act = menu.addAction('📖 책 보기 끄기' if self._book_view_active else '📖 책 보기')
        book_act.setCheckable(True)
        book_act.setChecked(self._book_view_active)
        book_act.triggered.connect(self._toggle_book_view)

        # 상단 툴바 자동 숨김 토글 (문서 넓게 보기)
        if hasattr(self, 'set_toolbar_autohide'):
            th_act = menu.addAction('🔻 상단 툴바 자동 숨김')
            th_act.setCheckable(True)
            th_act.setChecked(getattr(self, '_toolbar_autohide', False))
            th_act.triggered.connect(self.set_toolbar_autohide)

        gp = global_pos.toPoint() if hasattr(global_pos, "toPoint") else global_pos
        menu.exec(gp)


    def _ctx_toggle_tool(self, tool):
        """우클릭 메뉴에서 도구 선택 — 이미 활성인 도구면 '선택'으로 토글 off.
        선택 후 상단 툴바 버튼의 활성 표시도 함께 갱신한다."""
        if self._canvas.current_tool() is tool:
            self._annot_bar._select_tool_fallback()
        else:
            self._canvas.set_tool(tool)
            if hasattr(self._annot_bar, '_restore_active_btn'):
                self._annot_bar._restore_active_btn()

    def _delete_pending_annot(self, pa):
        pa.remove_from_scene()
        self._canvas.pending_layer().remove_uid(pa.uid)
        self._canvas.notify_pending_changed()


    def _delete_committed_annot(self, page_idx: int, xref: int):
        page = self._doc.fitz_page(page_idx)
        annots = page.annots()
        if annots is None:
            return
        for annot in annots:
            try:
                if annot.xref != xref:
                    continue
                page.delete_annot(annot)
                self._doc.mark_dirty()
                self._canvas._renderer.invalidate(page_idx)
                self._canvas.refresh_page()
                break
            except Exception:
                continue


    def _flatten_committed_annot(self, page_idx: int, xref: int, refresh: bool = True) -> bool:
        import fitz

        page = self._doc.fitz_page(page_idx)
        annots = page.annots()
        if annots is None:
            return False
        target = None
        for annot in annots:
            try:
                if annot.xref == xref:
                    target = annot
                    break
            except Exception:
                continue
        if target is None:
            return False
        try:
            rect = fitz.Rect(target.rect)
            pix = target.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=True)
            page.insert_image(rect, stream=pix.tobytes('png'), keep_proportion=False, overlay=True)
            page.delete_annot(target)
            self._doc.mark_dirty()
            self._canvas._renderer.invalidate(page_idx)
            if refresh:
                self._canvas.refresh_page()
            return True
        except Exception as exc:
            QMessageBox.warning(self, '플래튼 실패', f'어노테이션을 플래튼할 수 없습니다.\n{exc}')
            return False


    def _flatten_pending_annot(self, pa):
        page_idx = pa.page_index
        page = self._doc.fitz_page(page_idx)
        before = set()
        annots = page.annots()
        if annots is not None:
            for annot in annots:
                try:
                    before.add(annot.xref)
                except Exception:
                    continue
        try:
            pa.commit(page)
        except Exception as exc:
            QMessageBox.warning(self, '플래튼 실패', f'어노테이션을 플래튼할 수 없습니다.\n{exc}')
            return

        pa.remove_from_scene()
        self._canvas.pending_layer().remove_uid(pa.uid)
        self._canvas.notify_pending_changed()
        self._doc.mark_dirty()

        new_xref = None
        annots = page.annots()
        if annots is not None:
            for annot in annots:
                try:
                    if annot.xref not in before:
                        new_xref = annot.xref
                        break
                except Exception:
                    continue

        self._canvas._renderer.invalidate(page_idx)
        if new_xref is not None:
            if self._flatten_committed_annot(page_idx, new_xref, refresh=False):
                self._canvas.refresh_page()
                return
        self._canvas.refresh_page()


    def _insert_note(self, scene_pos):
        if not self._doc.is_open:
            return
        from PySide6.QtWidgets import QInputDialog, QGraphicsRectItem, QGraphicsItemGroup, QGraphicsTextItem
        from PySide6.QtGui import QPen, QBrush, QColor, QFont
        from utils.annot_mapper import scene_to_fitz_pt
        from utils.pending_layer import PendingAnnotation
        import fitz as _fitz

        text, ok = QInputDialog.getMultiLineText(self, '메모 입력', '메모 내용을 입력하세요:')
        if not ok or not text.strip():
            return
        text = text.strip()
        fitz_pt = scene_to_fitz_pt(scene_pos, self._canvas.zoom())
        rect = _fitz.Rect(fitz_pt.x, fitz_pt.y, fitz_pt.x + 20, fitz_pt.y + 20)
        pa = PendingAnnotation(
            uid=self._canvas.pending_layer().next_uid(),
            page_index=self._canvas.current_page(),
            tool_name='note',
            annot_type='text',
            fitz_rect=rect,
            text=text,
        )
        self._canvas.pending_layer().add(pa)
        self._doc.mark_dirty()
        off = self._canvas._page_offsets.get(self._canvas.current_page(), QPointF(0, 0))
        zoom = self._canvas.zoom()
        x = rect.x0 * zoom + off.x()
        y = rect.y0 * zoom + off.y()
        pw = 180.0
        ph = 60.0
        group = QGraphicsItemGroup()
        bg = QGraphicsRectItem(x, y, pw, ph)
        bg.setPen(QPen(QColor('#ffa000'), 1.5, Qt.PenStyle.DashLine))
        bg.setBrush(QBrush(QColor(255, 250, 200, 210)))
        group.addToGroup(bg)
        header = QGraphicsTextItem('📌 메모')
        hf = QFont('Malgun Gothic')
        hf.setPixelSize(16)
        hf.setBold(True)
        header.setFont(hf)
        header.setDefaultTextColor(QColor('#e65100'))
        header.setPos(x + 4, y + 2)
        group.addToGroup(header)
        body = QGraphicsTextItem(text)
        bf = QFont('Malgun Gothic')
        bf.setPixelSize(15)
        body.setFont(bf)
        body.setPos(x + 6, y + 22)
        body.setTextWidth(pw - 8)
        group.addToGroup(body)
        group.setZValue(20)
        self._canvas.scene().addItem(group)
        pa.q_item = group
        self._canvas.notify_pending_changed()


    def _insert_text(self, scene_pos):
        if not self._doc.is_open:
            return
        from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsItemGroup, QGraphicsTextItem
        from PySide6.QtGui import QPen, QBrush, QColor, QFont
        from utils.annot_mapper import scene_to_fitz_pt
        from utils.pending_layer import PendingAnnotation
        from tools.text_tool import _TextInsertDialog
        import fitz as _fitz

        text_tool = None
        if hasattr(self._annot_bar, "_tools"):
            text_tool = self._annot_bar._tools.get("text")
        default_family = getattr(text_tool, "_font_family", "Malgun Gothic")
        default_size = int(getattr(text_tool, "_font_size", 12))
        dlg = _TextInsertDialog(default_family, default_size, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        text = dlg.text().strip()
        if not text:
            return
        fontfile, fontname, qt_family = dlg.font_option()
        font_size = dlg.font_size()
        if text_tool is not None:
            text_tool._font_family = qt_family
            text_tool._font_size = font_size
        fitz_pt = scene_to_fitz_pt(scene_pos, self._canvas.zoom())
        lines_ = text.splitlines() or ['']
        longest = max(len(line) for line in lines_)
        w = max(180, longest * font_size * 0.62 + 12)
        h = max(font_size + 8, len(lines_) * (font_size + 4) + 8)
        rect = _fitz.Rect(fitz_pt.x, fitz_pt.y, fitz_pt.x + w, fitz_pt.y + h)
        pa = PendingAnnotation(
            uid=self._canvas.pending_layer().next_uid(),
            page_index=self._canvas.current_page(),
            tool_name='text',
            annot_type='direct_text',
            fitz_rect=rect,
            text=text,
            fontsize=float(font_size),
            fontname=fontname,
            fontfile=fontfile,
            text_color=(0.0, 0.0, 0.0),
            text_align=_fitz.TEXT_ALIGN_LEFT,
        )
        self._canvas.pending_layer().add(pa)
        self._doc.mark_dirty()
        off = self._canvas._page_offsets.get(self._canvas.current_page(), QPointF(0, 0))
        zoom = self._canvas.zoom()
        x = rect.x0 * zoom + off.x()
        y = rect.y0 * zoom + off.y()
        pw = rect.width * zoom
        ph = rect.height * zoom
        group = QGraphicsItemGroup()
        bg = QGraphicsRectItem(x, y, pw, ph)
        bg.setPen(QPen(QColor('#1a7fc1'), 1.5, Qt.PenStyle.DashLine))
        bg.setBrush(QBrush(QColor(255, 255, 200, 180)))
        group.addToGroup(bg)
        txt_item = QGraphicsTextItem(text)
        f = QFont(qt_family)
        f.setPixelSize(max(8, int(font_size * zoom)))
        txt_item.setFont(f)
        txt_item.setDefaultTextColor(QColor('#202020'))
        txt_item.setPos(x + 3, y + 1)
        txt_item.setTextWidth(max(1, pw - 6))
        group.addToGroup(txt_item)
        group.setZValue(20)
        self._canvas.scene().addItem(group)
        pa.q_item = group
        self._canvas.notify_pending_changed()

