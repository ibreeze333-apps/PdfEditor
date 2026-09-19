# tools/block_arrow_tool.py — 블록(채워진) 화살표 도구
from __future__ import annotations
import math
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPen, QBrush, QPainterPath
from PySide6.QtWidgets import QGraphicsPathItem
from tools.base_tool import BaseTool
from utils.annot_mapper import resolve_page_and_fitz_pt, scene_to_fitz_pt
from utils.annot_style import tool_style
from utils.pending_layer import PendingAnnotation


def _block_arrow_scene_path(x1: float, y1: float, x2: float, y2: float,
                             shaft_ratio: float = 0.38,
                             head_ratio: float = 0.35) -> QPainterPath | None:
    """화면 좌표로 블록 화살표 QPainterPath 반환."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 4:
        return None
    ux, uy = dx / length, dy / length
    px, py = -uy, ux  # 수직 단위 벡터

    head_w = max(10.0, length * 0.20)
    shaft_w = head_w * shaft_ratio
    head_len = min(length * head_ratio, head_w * 2.0)
    hx = x1 + ux * (length - head_len)
    hy = y1 + uy * (length - head_len)

    path = QPainterPath()
    path.moveTo(x1 + px * shaft_w,  y1 + py * shaft_w)
    path.lineTo(hx  + px * shaft_w,  hy  + py * shaft_w)
    path.lineTo(hx  + px * head_w,   hy  + py * head_w)
    path.lineTo(x2,                  y2)
    path.lineTo(hx  - px * head_w,   hy  - py * head_w)
    path.lineTo(hx  - px * shaft_w,  hy  - py * shaft_w)
    path.lineTo(x1 - px * shaft_w,   y1 - py * shaft_w)
    path.closeSubpath()
    return path


def _block_arrow_fitz_points(fx1: float, fy1: float, fx2: float, fy2: float,
                              shaft_ratio: float = 0.38,
                              head_ratio: float = 0.35) -> list[tuple] | None:
    """fitz(PDF) 좌표로 블록 화살표 폴리곤 포인트 반환."""
    dx, dy = fx2 - fx1, fy2 - fy1
    length = math.hypot(dx, dy)
    if length < 2:
        return None
    ux, uy = dx / length, dy / length
    px, py = -uy, ux

    head_w = max(6.0, length * 0.20)
    shaft_w = head_w * shaft_ratio
    head_len = min(length * head_ratio, head_w * 2.0)
    hx = fx1 + ux * (length - head_len)
    hy = fy1 + uy * (length - head_len)

    return [
        (fx1 + px * shaft_w,  fy1 + py * shaft_w),
        (hx  + px * shaft_w,  hy  + py * shaft_w),
        (hx  + px * head_w,   hy  + py * head_w),
        (fx2,                  fy2),
        (hx  - px * head_w,   hy  - py * head_w),
        (hx  - px * shaft_w,  hy  - py * shaft_w),
        (fx1 - px * shaft_w,  fy1 - py * shaft_w),
    ]


class BlockArrowTool(BaseTool):
    name = 'block_arrow'
    label = '🔶 블록 화살표'
    cursor = Qt.CursorShape.CrossCursor
    shortcut = None

    def __init__(self):
        self._start: QPointF | None = None
        self._preview: QGraphicsPathItem | None = None

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def on_press(self, pos, event, view):
        self._start = pos
        st = tool_style(self.name)
        color = st.color
        item = QGraphicsPathItem()
        pen = QPen(color, 1)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        item.setPen(pen)
        item.setBrush(QBrush(color))
        item.setZValue(10)
        view.scene().addItem(item)
        self._preview = item

    def on_move(self, pos, event, view):
        if not (self._start and self._preview):
            return
        path = _block_arrow_scene_path(
            self._start.x(), self._start.y(), pos.x(), pos.y()
        )
        if path:
            self._preview.setPath(path)

    def on_release(self, pos, event, view):
        if not self._start:
            return
        start = self._start
        preview = self._preview
        self._start = None
        self._preview = None

        page_idx, fp1 = resolve_page_and_fitz_pt(view, start)
        offset = view.page_offset(page_idx)
        fp2 = scene_to_fitz_pt(pos, view.zoom(), offset)

        fitz_pts = _block_arrow_fitz_points(fp1.x, fp1.y, fp2.x, fp2.y)
        if fitz_pts is None:
            if preview:
                view.scene().removeItem(preview)
            return

        st = tool_style(self.name)
        fill = st.fitz_color()

        pa = PendingAnnotation(
            uid=view.pending_layer().next_uid(),
            page_index=page_idx,
            tool_name=self.name,
            annot_type='polygon',
            points=[fitz_pts],
            stroke_color=fill,
            fill_color=fill,
            border_width=0,
            q_item=preview,
        )
        view.pending_layer().add(pa)
        view.doc().mark_dirty()
        view.notify_pending_changed()

    def on_cancel(self, view):
        if self._preview:
            view.scene().removeItem(self._preview)
            self._preview = None
        self._start = None
