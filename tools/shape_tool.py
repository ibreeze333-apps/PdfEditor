# tools/shape_tool.py — 도형 (사각형 / 원 / 삼각형 / 오각형 / 육각형)
from __future__ import annotations
import math
import fitz
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPen, QBrush, QColor, QPainterPath
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsPathItem
from tools.base_tool import BaseTool
from utils.annot_mapper import resolve_page_and_fitz_rect
from utils.annot_style import scene_dashes, scene_width, tool_style
from utils.pending_layer import PendingAnnotation


class ShapeTool(BaseTool):
    name     = 'shape'
    label    = '도형'
    cursor   = Qt.CursorShape.CrossCursor
    shortcut = 'S'

    shape_type = 'rect'
    fill_mode: str = 'none'
    fill_color: QColor | None = None

    def __init__(self):
        self._start: QPointF | None = None
        self._preview = None
        self.fill_transparent = True

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def _get_fill_fitz(self, st) -> list[float] | None:
        if self.fill_mode == 'color':
            c = self.fill_color if self.fill_color is not None else st.color
            return [c.redF(), c.greenF(), c.blueF()]
        if self.fill_mode == 'white':
            return [1.0, 1.0, 1.0]
        return None

    def _make_pen(self, st, view=None) -> QPen:
        w = scene_width(st.width, view) if view is not None else max(0.5, st.width)
        pen = QPen(st.color, w)
        if st.dashes:
            pen.setDashPattern(scene_dashes(st.dashes, st.width))
        return pen

    def _polygon_points(self, rect, sides: int) -> list[tuple[float, float]]:
        cx, cy = rect.center().x(), rect.center().y()
        rx, ry = rect.width() / 2.0, rect.height() / 2.0
        start_angle = -math.pi / 2.0
        points = []
        for i in range(sides):
            ang = start_angle + (2 * math.pi * i / sides)
            points.append((cx + rx * math.cos(ang), cy + ry * math.sin(ang)))
        return points

    def _set_polygon_preview(self, rect: QRectF, sides: int):
        path = QPainterPath()
        pts = self._polygon_points(rect, sides)
        path.moveTo(*pts[0])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        self._preview.setPath(path)

    def on_press(self, pos, event, view):
        self._start = pos
        st = tool_style(self.name)
        fill = self._get_fill_fitz(st)
        brush = (QBrush(QColor(int(fill[0]*255), int(fill[1]*255), int(fill[2]*255), 80))
                 if fill else QBrush(Qt.BrushStyle.NoBrush))
        if self.shape_type == 'circle':
            item = QGraphicsEllipseItem()
        elif self.shape_type in ('triangle', 'pentagon', 'hexagon'):
            item = QGraphicsPathItem()
        else:
            item = QGraphicsRectItem()
        item.setPen(self._make_pen(st, view))
        item.setBrush(brush)
        item.setZValue(10)
        view.scene().addItem(item)
        self._preview = item

    def on_move(self, pos, event, view):
        if not (self._start and self._preview):
            return
        rect = QRectF(self._start, pos).normalized()
        if self.shape_type == 'triangle':
            self._set_polygon_preview(rect, 3)
        elif self.shape_type == 'pentagon':
            self._set_polygon_preview(rect, 5)
        elif self.shape_type == 'hexagon':
            self._set_polygon_preview(rect, 6)
        else:
            self._preview.setRect(rect)

    def on_release(self, pos, event, view):
        if not self._start:
            return
        rect_q = QRectF(self._start, pos).normalized()
        preview = self._preview
        self._preview = None
        self._start = None
        if rect_q.width() < 4 or rect_q.height() < 4:
            if preview:
                view.scene().removeItem(preview)
            return
        page_index, fitz_rect = resolve_page_and_fitz_rect(view, rect_q)
        st = tool_style(self.name)
        fill = self._get_fill_fitz(st)

        if self.shape_type == 'circle':
            at = 'circle'
            points = None
        elif self.shape_type == 'triangle':
            x0, y0, x1, y1 = fitz_rect
            cx = (x0 + x1) / 2
            at = 'polygon'
            points = [[(cx, y0), (x1, y1), (x0, y1)]]
            fitz_rect = None
        elif self.shape_type in ('pentagon', 'hexagon'):
            x0, y0, x1, y1 = fitz_rect
            rect = QRectF(x0, y0, x1 - x0, y1 - y0)
            sides = 5 if self.shape_type == 'pentagon' else 6
            at = 'polygon'
            points = [[(x, y) for x, y in self._polygon_points(rect, sides)]]
            fitz_rect = None
        else:
            at = 'rect'
            points = None

        pa = PendingAnnotation(
            uid=view.pending_layer().next_uid(),
            page_index=page_index,
            tool_name=self.name,
            annot_type=at,
            fitz_rect=fitz_rect,
            points=points,
            stroke_color=st.fitz_color(),
            fill_color=fill,
            border_width=max(0.5, st.width),
            dashes=st.dashes if st.dashes else None,
            q_item=preview,
        )
        view.pending_layer().add(pa)
        view.doc().mark_dirty()
        view.notify_pending_changed()
