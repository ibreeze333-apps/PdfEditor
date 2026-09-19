# tools/underline_tool.py — 밑줄 (직선 / 물결)
from __future__ import annotations
import math
import fitz
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPen, QPainterPath
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsPathItem
from tools.base_tool import BaseTool
from utils.annot_mapper import resolve_page_and_fitz_rect
from utils.annot_style import scene_dashes, scene_width, tool_style
from utils.pending_layer import PendingAnnotation


class UnderlineTool(BaseTool):
    name     = 'underline'
    label    = '밑줄'
    cursor   = Qt.CursorShape.IBeamCursor
    shortcut = 'U'

    def __init__(self):
        self._start: QPointF | None = None
        self._preview = None   # QGraphicsLineItem | QGraphicsPathItem

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def on_press(self, pos, event, view):
        self._start = pos
        st = tool_style(self.name)
        if st.is_wavy():
            item = QGraphicsPathItem()
            item.setPen(QPen(st.color, scene_width(st.width, view)))
        else:
            item = QGraphicsLineItem()
            pen = QPen(st.color, scene_width(st.width, view))
            if st.dashes:
                pen.setDashPattern(scene_dashes(st.dashes, st.width))
            item.setPen(pen)
        item.setZValue(10)
        view.scene().addItem(item)
        self._preview = item

    def on_move(self, pos, event, view):
        if not (self._start and self._preview):
            return
        rect = QRectF(self._start, pos).normalized()
        y    = rect.bottom()
        st   = tool_style(self.name)
        if st.is_wavy():
            path = _make_wavy_path(rect.left(), y, rect.right(),
                                   amplitude=3.0, period=10.0)
            self._preview.setPath(path)
        else:
            self._preview.setLine(rect.left(), y, rect.right(), y)

    def on_release(self, pos, event, view):
        if not self._start:
            return
        preview = self._preview
        self._preview = None
        rect_q  = QRectF(self._start, pos).normalized()
        self._start = None
        if rect_q.width() < 3:
            if preview:
                view.scene().removeItem(preview)
            return

        page_idx, fitz_rect = resolve_page_and_fitz_rect(view, rect_q)
        y         = fitz_rect.y1
        st        = tool_style(self.name)

        if st.is_wavy():
            pts    = _make_wavy_fitz_pts(fitz_rect.x0, y, fitz_rect.x1,
                                         amplitude=2.0, period=8.0)
            points = [pts]
            dashes = None
        else:
            points = [[(fitz_rect.x0, y), (fitz_rect.x1, y)]]
            dashes = st.dashes if st.dashes else None

        pa = PendingAnnotation(
            uid          = view.pending_layer().next_uid(),
            page_index   = page_idx,
            tool_name    = self.name,
            annot_type   = 'ink',
            points       = points,
            stroke_color = st.fitz_color(),
            border_width = st.width,
            dashes       = dashes,
            q_item       = preview,
        )
        view.pending_layer().add(pa)
        view.doc().mark_dirty()
        view.notify_pending_changed()


# ── 헬퍼: 물결선 생성 ────────────────────────────────────────────────────

def _make_wavy_path(x0: float, y: float, x1: float,
                    amplitude: float = 3.0,
                    period: float = 10.0) -> QPainterPath:
    """Qt 프리뷰용 sine 파형 QPainterPath."""
    path  = QPainterPath()
    steps = max(2, int((x1 - x0) / 2))
    for i in range(steps + 1):
        t  = i / steps
        x  = x0 + t * (x1 - x0)
        yv = y + amplitude * math.sin(2 * math.pi * x / period)
        if i == 0:
            path.moveTo(x, yv)
        else:
            path.lineTo(x, yv)
    return path


def _make_wavy_fitz_pts(x0: float, y: float, x1: float,
                        amplitude: float = 2.0,
                        period: float = 8.0) -> list[tuple[float, float]]:
    """fitz ink annot용 sine 파형 점 목록."""
    steps = max(4, int(x1 - x0))   # ~1pt 간격
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t  = i / steps
        x  = x0 + t * (x1 - x0)
        yv = y + amplitude * math.sin(2 * math.pi * x / period)
        pts.append((x, yv))
    return pts
