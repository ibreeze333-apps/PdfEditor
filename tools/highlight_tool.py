# tools/highlight_tool.py — 형광펜
# 이미지 PDF 포함 모든 PDF에서 동작하도록 add_rect_annot 사용
from __future__ import annotations
import fitz
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPen, QBrush, QColor
from PySide6.QtWidgets import QGraphicsRectItem
from tools.base_tool import BaseTool
from utils.annot_mapper import resolve_page_and_fitz_rect
from utils.annot_style import tool_style
from utils.pending_layer import PendingAnnotation


class HighlightTool(BaseTool):
    name     = 'highlight'
    label    = '형광펜'
    cursor   = Qt.CursorShape.CrossCursor
    shortcut = 'H'

    def __init__(self):
        self._start: QPointF | None = None
        self._preview: QGraphicsRectItem | None = None
        self._fixed_height_enabled = False
        self._fixed_height_pts = 12.0
        self._last_height_pts = 12.0

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def set_fixed_height_enabled(self, enabled: bool):
        self._fixed_height_enabled = bool(enabled)
        if self._fixed_height_enabled:
            self._fixed_height_pts = max(2.0, float(self._last_height_pts))

    def _rect_from_drag(self, pos, view) -> QRectF:
        if self._start is None:
            return QRectF()
        if self._fixed_height_enabled:
            fixed_h = max(2.0, self._fixed_height_pts * view.zoom())
            y2 = self._start.y() + fixed_h if pos.y() >= self._start.y() else self._start.y() - fixed_h
            return QRectF(self._start, QPointF(pos.x(), y2)).normalized()
        return QRectF(self._start, pos).normalized()

    def on_press(self, pos, event, view):
        self._start = pos
        st    = tool_style(self.name)
        color = QColor(st.color)
        color.setAlphaF(st.opacity)
        item = QGraphicsRectItem()
        item.setPen(QPen(Qt.PenStyle.NoPen))
        item.setBrush(QBrush(color))
        item.setZValue(10)
        view.scene().addItem(item)
        self._preview = item

    def on_move(self, pos, event, view):
        if self._start and self._preview:
            self._preview.setRect(self._rect_from_drag(pos, view))

    def on_release(self, pos, event, view):
        if not self._start:
            return
        rect_q  = self._rect_from_drag(pos, view)
        preview = self._preview
        self._preview = None
        self._start   = None
        # 너비만 체크 — 가는 수평 드래그도 허용
        if rect_q.width() < 2:
            if preview:
                view.scene().removeItem(preview)
            return
        st        = tool_style(self.name)
        page_index, fitz_rect = resolve_page_and_fitz_rect(view, rect_q)
        self._last_height_pts = max(2.0, float(fitz_rect.height))
        if self._fixed_height_enabled:
            self._fixed_height_pts = self._last_height_pts
        c         = st.fitz_color()
        pa = PendingAnnotation(
            uid          = view.pending_layer().next_uid(),
            page_index   = page_index,
            tool_name    = self.name,
            annot_type   = 'rect',
            fitz_rect    = fitz_rect,
            stroke_color = c,
            fill_color   = c,
            opacity      = st.opacity,
            border_width = max(0.1, st.width),
            q_item       = preview,   # 프리뷰 아이템을 그대로 유지
        )
        view.pending_layer().add(pa)
        view.doc().mark_dirty()
        view.notify_pending_changed()
