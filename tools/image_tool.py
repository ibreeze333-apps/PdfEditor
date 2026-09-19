# tools/image_tool.py — 이미지 삽입
from __future__ import annotations
import fitz
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QMouseEvent, QPen, QColor
from PySide6.QtWidgets import QGraphicsRectItem, QFileDialog
from tools.base_tool import BaseTool
from utils.annot_mapper import resolve_page_and_fitz_rect
from utils.pending_layer import PendingAnnotation


class ImageTool(BaseTool):
    name     = 'image'
    label    = '이미지 삽입'
    cursor   = Qt.CursorShape.CrossCursor
    shortcut = 'I'

    def __init__(self):
        self._start: QPointF | None = None
        self._preview: QGraphicsRectItem | None = None
        self._pending_path: str = ''

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)
        # 도구 활성화 즉시 파일 선택
        path, _ = QFileDialog.getOpenFileName(
            view, '삽입할 이미지 선택', '',
            '이미지 (*.png *.jpg *.jpeg *.bmp *.webp *.tiff)')
        self._pending_path = path

    def on_press(self, pos, event, view):
        if not self._pending_path:
            return
        self._start = pos
        item = QGraphicsRectItem()
        item.setPen(QPen(QColor(100, 100, 255), 2,
                         Qt.PenStyle.DashLine))
        item.setZValue(10)
        view.scene().addItem(item)
        self._preview = item

    def on_move(self, pos, event, view):
        if self._start and self._preview:
            self._preview.setRect(
                QRectF(self._start, pos).normalized())

    def on_release(self, pos, event, view):
        if not self._start or not self._pending_path:
            return
        rect_q       = QRectF(self._start, pos).normalized()
        preview      = self._preview
        self._preview = None
        self._start   = None
        img_path      = self._pending_path
        self._pending_path = ''
        if rect_q.width() < 10 or rect_q.height() < 10:
            if preview:
                view.scene().removeItem(preview)
            return
        page_idx, fitz_rect = resolve_page_and_fitz_rect(view, rect_q)
        # 이미지 실제 픽스맵으로 프리뷰 교체
        if preview:
            view.scene().removeItem(preview)
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QGraphicsPixmapItem
        pxm = QPixmap(img_path)
        if not pxm.isNull():
            pxm = pxm.scaled(
                max(1, int(fitz_rect.width * view.zoom())),
                max(1, int(fitz_rect.height * view.zoom())),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            offset = view.page_offset(page_idx)
            img_item = QGraphicsPixmapItem(pxm)
            img_item.setPos(fitz_rect.x0 * view.zoom() + offset.x(),
                            fitz_rect.y0 * view.zoom() + offset.y())
            img_item.setZValue(20)
            view.scene().addItem(img_item)
            q_item = img_item
        else:
            q_item = None

        pa = PendingAnnotation(
            uid        = view.pending_layer().next_uid(),
            page_index = page_idx,
            tool_name  = self.name,
            annot_type = 'image',
            fitz_rect  = fitz_rect,
            image_path = img_path,
            q_item     = q_item,
        )
        view.pending_layer().add(pa)
        view.doc().mark_dirty()
        view.notify_pending_changed()
