from __future__ import annotations

import math

import fitz
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsPathItem

from tools.base_tool import BaseTool
from utils.annot_mapper import resolve_page_and_fitz_rect
from utils.annot_style import scene_dashes, scene_width, tool_style
from utils.pending_layer import PendingAnnotation


def _make_wavy_path(x0: float, y: float, x1: float,
                    amplitude: float = 3.0,
                    period: float = 10.0) -> QPainterPath:
    path = QPainterPath()
    steps = max(2, int((x1 - x0) / 2))
    for i in range(steps + 1):
        t = i / steps
        x = x0 + t * (x1 - x0)
        yv = y + amplitude * math.sin(2 * math.pi * x / period)
        if i == 0:
            path.moveTo(x, yv)
        else:
            path.lineTo(x, yv)
    return path


def _make_wavy_pts(x0: float, y: float, x1: float,
                   amplitude: float = 2.0,
                   period: float = 8.0) -> list[tuple[float, float]]:
    steps = max(4, int(x1 - x0))
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        x = x0 + t * (x1 - x0)
        yv = y + amplitude * math.sin(2 * math.pi * x / period)
        pts.append((x, yv))
    return pts


class StrikethroughTool(BaseTool):
    name = 'strikethrough'
    label = '취소선'
    cursor = Qt.CursorShape.IBeamCursor
    shortcut = 'K'

    def __init__(self):
        self._start: QPointF | None = None
        self._preview = None

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def on_press(self, pos, event, view):
        self._start = pos
        style = tool_style(self.name)
        if style.is_wavy():
            item = QGraphicsPathItem()
            item.setPen(QPen(style.color, scene_width(style.width, view)))
        else:
            item = QGraphicsLineItem()
            pen = QPen(style.color, scene_width(style.width, view))
            if style.dashes:
                pen.setDashPattern(scene_dashes(style.dashes, style.width))
            item.setPen(pen)
        item.setZValue(10)
        view.scene().addItem(item)
        self._preview = item

    def on_move(self, pos, event, view):
        if not (self._start and self._preview):
            return
        rect = QRectF(self._start, pos).normalized()
        mid_y = rect.center().y()
        style = tool_style(self.name)
        if style.is_wavy():
            self._preview.setPath(_make_wavy_path(rect.left(), mid_y, rect.right()))
        else:
            self._preview.setLine(rect.left(), mid_y, rect.right(), mid_y)

    def on_release(self, pos, event, view):
        if not self._start:
            return
        preview = self._preview
        self._preview = None
        rect_q = QRectF(self._start, pos).normalized()
        self._start = None
        if rect_q.width() < 3:
            if preview:
                view.scene().removeItem(preview)
            return
        page_idx, fitz_rect = resolve_page_and_fitz_rect(view, rect_q)
        y = (fitz_rect.y0 + fitz_rect.y1) / 2
        style = tool_style(self.name)
        if style.is_wavy():
            points = [_make_wavy_pts(fitz_rect.x0, y, fitz_rect.x1)]
            dashes = None
        else:
            points = [[(fitz_rect.x0, y), (fitz_rect.x1, y)]]
            dashes = style.dashes if style.dashes else None
        pending = PendingAnnotation(
            uid=view.pending_layer().next_uid(),
            page_index=page_idx,
            tool_name=self.name,
            annot_type='ink',
            points=points,
            stroke_color=style.fitz_color(),
            border_width=style.width,
            dashes=dashes,
            q_item=preview,
        )
        view.pending_layer().add(pending)
        view.doc().mark_dirty()
        view.notify_pending_changed()
