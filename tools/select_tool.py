from __future__ import annotations

import fitz
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QKeyEvent, QMouseEvent, QPen, QBrush
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsLineItem, QInputDialog, QToolTip

from tools.base_tool import BaseTool
from utils.annot_mapper import scene_to_fitz_pt, resolve_page_and_fitz_pt
from utils.pending_layer import PendingAnnotation
from utils.errlog import swallowed

_ANNOT_TEXT = 0
_ANNOT_FREE_TEXT = 2
_ANNOT_INK = 15
_TOLERANCE = 6
_SELECT_TOLERANCE = 12
_HANDLE_SIZE = 18.0
_MIN_SIZE = 4.0
_ROT_HANDLE_R = 8.0       # 회전 핸들 반지름 (scene px)
_ROT_HANDLE_OFFSET = 32.0 # 선택 박스 상단에서 위로 띄우는 거리 (scene px)


def _move_ink_annot(page: fitz.Page, annot: fitz.Annot, dx: float, dy: float) -> fitz.Annot | None:
    try:
        strokes = annot.vertices
        if not strokes:
            return None
        if strokes and isinstance(strokes[0], (list, tuple)) and len(strokes[0]) > 0:
            if isinstance(strokes[0][0], (list, tuple)):
                moved = [[(x + dx, y + dy) for x, y in stroke] for stroke in strokes]
            else:
                moved = [[(x + dx, y + dy) for x, y in strokes]]
        else:
            return None
        colors = annot.colors
        border_width = annot.border.get('width', 1.5)
        page.delete_annot(annot)
        new_annot = page.add_ink_annot(moved)
        if colors.get('stroke'):
            new_annot.set_colors(stroke=colors['stroke'])
        new_annot.set_border(width=max(1, border_width))
        new_annot.update()
        return new_annot
    except Exception as exc:
        print(f'[_move_ink_annot] {exc}')
        return None


def _pending_geometry_rect(pa: PendingAnnotation) -> fitz.Rect | None:
    if pa.fitz_rect is not None:
        return fitz.Rect(pa.fitz_rect)
    if pa.p1 is not None and pa.p2 is not None:
        return fitz.Rect(min(pa.p1.x, pa.p2.x), min(pa.p1.y, pa.p2.y), max(pa.p1.x, pa.p2.x), max(pa.p1.y, pa.p2.y))
    if pa.points:
        pts = [pt for stroke in pa.points for pt in stroke]
        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            return fitz.Rect(min(xs), min(ys), max(xs), max(ys))
    return None


class SelectTool(BaseTool):
    name = 'select'
    label = '선택'
    cursor = Qt.CursorShape.ArrowCursor
    shortcut = 'V'

    def __init__(self):
        self._sel_pending: PendingAnnotation | None = None
        self._sel_xref: int | None = None
        self._sel_rect: fitz.Rect | None = None
        self._sel_stamp_index: int = -1
        self._drag_start: QPointF | None = None
        self._was_dragging = False
        self._sel_item: QGraphicsRectItem | None = None
        self._drag_mode = 'move'
        self._resize_handle: str | None = None
        self._drag_bbox_start: fitz.Rect | None = None
        self._pending_snapshot: dict | None = None
        # 회전 핸들
        self._rot_handle_item: QGraphicsEllipseItem | None = None
        self._rot_line_item: QGraphicsLineItem | None = None
        self._rot_handle_scene_pos: QPointF | None = None
        self._rot_center_scene: QPointF | None = None
        self._rot_start_angle: float = 0.0
        self._rot_center_fitz: fitz.Point | None = None
        # 모서리 크기조절 핸들 사각형 아이템들
        self._handle_items: list = []
        # 커밋된 어노테이션 이동 시 누적 이동량 (scene px)
        self._accum_delta: QPointF = QPointF(0, 0)
        # 현재 다루는 페이지 — 스크롤/양면 모드에서 클릭한 페이지 기준으로
        # 좌표를 변환해야 하므로 (current_page 와 다를 수 있음)
        self._sel_page: int | None = None

    # ── 페이지/오프셋 헬퍼 (스크롤·양면 모드 좌표 보정) ────────────────
    def _page(self, view) -> int:
        return self._sel_page if self._sel_page is not None else view.current_page()

    def _offset(self, view) -> QPointF:
        return view.page_offset(self._page(view))

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.ScrollHandDrag)

    def deactivate(self, view):
        super().deactivate(view)
        self._remove_sel_item(view)
        self._sel_xref = None
        self._sel_rect = None
        self._sel_pending = None
        self._drag_mode = 'move'
        self._resize_handle = None
        self._drag_bbox_start = None
        self._pending_snapshot = None
        view.setDragMode(view.DragMode.NoDrag)

    @staticmethod
    def _is_qt_valid(obj) -> bool:
        try:
            from shiboken6 import isValid
            return isValid(obj)
        except Exception:
            swallowed()
        try:
            obj.scene()
            return True
        except RuntimeError:
            return False

    def _sel_item_alive(self) -> bool:
        if self._sel_item is None:
            return False
        if not self._is_qt_valid(self._sel_item):
            self._sel_item = None
            return False
        return True

    def _remove_sel_item(self, view):
        for attr in ('_rot_handle_item', '_rot_line_item'):
            item = getattr(self, attr, None)
            if item is not None:
                try:
                    s = item.scene()
                    if s:
                        s.removeItem(item)
                except Exception:
                    swallowed()
                setattr(self, attr, None)
        self._rot_handle_scene_pos = None
        for h in self._handle_items:
            try:
                s = h.scene()
                if s:
                    s.removeItem(h)
            except Exception:
                swallowed()
        self._handle_items = []
        if not self._sel_item_alive():
            self._sel_item = None
            return
        try:
            scene = self._sel_item.scene()
            if scene is not None:
                scene.removeItem(self._sel_item)
        except Exception:
            swallowed()
        self._sel_item = None

    def _draw_sel_item(self, rect_obj, view):
        self._remove_sel_item(view)
        if isinstance(rect_obj, QRectF):
            rect = rect_obj
        else:
            fitz_rect = rect_obj
            zoom = view.zoom()
            offset = self._offset(view)
            rect = QRectF(
                fitz_rect.x0 * zoom + offset.x(),
                fitz_rect.y0 * zoom + offset.y(),
                fitz_rect.width * zoom,
                fitz_rect.height * zoom,
            )
        item = QGraphicsRectItem(rect)
        item.setPen(QPen(QColor(30, 130, 220, 210), 1.4))
        item.setZValue(200)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setAcceptHoverEvents(False)
        view.scene().addItem(item)
        self._sel_item = item

        # 모서리 크기조절 핸들 — 잡을 수 있는 위치를 눈에 보이게
        hs = 9.0
        for cx, cy in ((rect.left(), rect.top()), (rect.right(), rect.top()),
                       (rect.left(), rect.bottom()), (rect.right(), rect.bottom())):
            h = QGraphicsRectItem(cx - hs / 2, cy - hs / 2, hs, hs)
            h.setPen(QPen(QColor(30, 130, 220), 1.2))
            h.setBrush(QBrush(QColor(255, 255, 255, 240)))
            h.setZValue(201)
            h.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            view.scene().addItem(h)
            self._handle_items.append(h)

        # 회전 핸들 (선택박스 상단 중앙 위)
        hx = rect.center().x()
        hy = rect.top() - _ROT_HANDLE_OFFSET
        line = QGraphicsLineItem(hx, rect.top(), hx, hy)
        line.setPen(QPen(QColor(30, 130, 220), 1.0))
        line.setZValue(200)
        line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        view.scene().addItem(line)
        self._rot_line_item = line

        handle = QGraphicsEllipseItem(hx - _ROT_HANDLE_R, hy - _ROT_HANDLE_R,
                                      _ROT_HANDLE_R * 2, _ROT_HANDLE_R * 2)
        handle.setPen(QPen(QColor(30, 130, 220), 1.5))
        handle.setBrush(QBrush(QColor(255, 255, 255, 220)))
        handle.setZValue(201)
        handle.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        view.scene().addItem(handle)
        self._rot_handle_item = handle
        self._rot_handle_scene_pos = QPointF(hx, hy)

    def _shift_sel_items(self, dx: float, dy: float):
        """드래그 중 선택 프레임을 재생성하지 않고 그대로 이동 — 부드러운 이동감."""
        items = [self._sel_item, self._rot_line_item, self._rot_handle_item] + self._handle_items
        for it in items:
            if it is None:
                continue
            try:
                it.moveBy(dx, dy)
            except RuntimeError:
                swallowed()
        if self._rot_handle_scene_pos is not None:
            self._rot_handle_scene_pos = QPointF(
                self._rot_handle_scene_pos.x() + dx,
                self._rot_handle_scene_pos.y() + dy)

    # 실제 사각형 좌표로 다뤄야 하는 타입 — 그림자/테이프/아이콘 여백이 포함된
    # 씬 bounding rect 대신 순수 fitz_rect 기준으로 선택·크기조절한다
    _RECT_GEOMETRY_TYPES = ('text', 'direct_text', 'freetext', 'index_tab')

    @classmethod
    def _uses_scene_pending_rect(cls, pending: PendingAnnotation) -> bool:
        if pending.annot_type in cls._RECT_GEOMETRY_TYPES:
            return False
        return getattr(pending, 'q_item', None) is not None

    def _pending_scene_rect(self, pending: PendingAnnotation, view, margin: float = 0.0) -> QRectF | None:
        if self._uses_scene_pending_rect(pending) and getattr(pending, 'q_item', None) is not None and self._is_qt_valid(pending.q_item):
            try:
                return pending.q_item.sceneBoundingRect().adjusted(-margin, -margin, margin, margin)
            except Exception:
                swallowed()
        # 사각형 타입은 padding 없는 정확한 rect 사용 (핸들 위치가 시각적 모서리와 일치)
        if pending.annot_type in self._RECT_GEOMETRY_TYPES:
            bbox = _pending_geometry_rect(pending)
        else:
            bbox = pending.bounding_fitz_rect()
        if bbox is None:
            return None
        zoom = view.zoom()
        offset = self._offset(view)
        return QRectF(
            bbox.x0 * zoom + offset.x() - margin,
            bbox.y0 * zoom + offset.y() - margin,
            bbox.width * zoom + 2 * margin,
            bbox.height * zoom + 2 * margin,
        )

    def _scene_rect_to_fitz_rect(self, scene_rect: QRectF | None, view) -> fitz.Rect | None:
        if scene_rect is None:
            return None
        zoom = view.zoom()
        offset = self._offset(view)
        return fitz.Rect(
            (scene_rect.x() - offset.x()) / zoom,
            (scene_rect.y() - offset.y()) / zoom,
            (scene_rect.x() + scene_rect.width() - offset.x()) / zoom,
            (scene_rect.y() + scene_rect.height() - offset.y()) / zoom,
        )

    def _find_pending(self, scene_pos: QPointF, view) -> PendingAnnotation | None:
        # 스크롤/양면 모드: 클릭한 씬 위치의 페이지를 찾아 그 페이지 좌표로 검사
        page, fitz_pt = resolve_page_and_fitz_pt(view, scene_pos)
        for pending in reversed(view.pending_layer().for_page(page)):
            if self._uses_scene_pending_rect(pending) and getattr(pending, 'q_item', None) is not None and self._is_qt_valid(pending.q_item):
                try:
                    scene_rect = pending.q_item.sceneBoundingRect().adjusted(-12.0, -12.0, 12.0, 12.0)
                    if scene_rect.contains(scene_pos):
                        return pending
                except Exception:
                    swallowed()
            bbox = pending.bounding_fitz_rect()
            if bbox is None:
                continue
            if bbox.x0 - _SELECT_TOLERANCE <= fitz_pt.x <= bbox.x1 + _SELECT_TOLERANCE and bbox.y0 - _SELECT_TOLERANCE <= fitz_pt.y <= bbox.y1 + _SELECT_TOLERANCE:
                return pending
        return None

    def _find_annot(self, scene_pos: QPointF, view) -> fitz.Annot | None:
        if not view.doc().is_open:
            return None
        page_idx, fitz_pt = resolve_page_and_fitz_pt(view, scene_pos)
        try:
            page = view.doc().fitz_page(page_idx)
        except Exception:
            return None
        for annot in list(page.annots()):
            try:
                rect = annot.rect
            except Exception:
                continue
            if rect.x0 - _SELECT_TOLERANCE <= fitz_pt.x <= rect.x1 + _SELECT_TOLERANCE and rect.y0 - _SELECT_TOLERANCE <= fitz_pt.y <= rect.y1 + _SELECT_TOLERANCE:
                return annot
        return None

    def _resize_handle_at(self, fitz_pt: fitz.Point, rect: fitz.Rect | None) -> str | None:
        if rect is None or rect.width < 1e-3 or rect.height < 1e-3:
            return None
        handles = {
            'nw': (rect.x0, rect.y0),
            'ne': (rect.x1, rect.y0),
            'sw': (rect.x0, rect.y1),
            'se': (rect.x1, rect.y1),
        }
        tol = max(_HANDLE_SIZE, float(self._sel_pending.border_width if self._sel_pending else 0.0) * 4.0)
        for name, (hx, hy) in handles.items():
            if abs(fitz_pt.x - hx) <= tol and abs(fitz_pt.y - hy) <= tol:
                return name
        return None

    def _pending_resize_handle_at(self, fitz_pt: fitz.Point, pending: PendingAnnotation, rect: fitz.Rect | None) -> str | None:
        if pending.p1 is not None and pending.p2 is not None:
            tol = max(_HANDLE_SIZE, float(pending.border_width) * 4.0)
            if abs(fitz_pt.x - pending.p1.x) <= tol and abs(fitz_pt.y - pending.p1.y) <= tol:
                return 'p1'
            if abs(fitz_pt.x - pending.p2.x) <= tol and abs(fitz_pt.y - pending.p2.y) <= tol:
                return 'p2'
        return self._resize_handle_at(fitz_pt, rect)

    @staticmethod
    def _cursor_for_handle(handle: str | None):
        if handle in ('nw', 'se'):
            return Qt.CursorShape.SizeFDiagCursor
        if handle in ('ne', 'sw'):
            return Qt.CursorShape.SizeBDiagCursor
        return Qt.CursorShape.SizeAllCursor

    def _resize_rect_from_handle(self, source: fitz.Rect, handle: str, fitz_pt: fitz.Point) -> fitz.Rect:
        x0, y0, x1, y1 = source.x0, source.y0, source.x1, source.y1
        if handle == 'nw':
            x0 = min(fitz_pt.x, x1 - _MIN_SIZE)
            y0 = min(fitz_pt.y, y1 - _MIN_SIZE)
        elif handle == 'ne':
            x1 = max(fitz_pt.x, x0 + _MIN_SIZE)
            y0 = min(fitz_pt.y, y1 - _MIN_SIZE)
        elif handle == 'sw':
            x0 = min(fitz_pt.x, x1 - _MIN_SIZE)
            y1 = max(fitz_pt.y, y0 + _MIN_SIZE)
        else:
            x1 = max(fitz_pt.x, x0 + _MIN_SIZE)
            y1 = max(fitz_pt.y, y0 + _MIN_SIZE)
        return fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def _is_on_rot_handle(self, pos: QPointF) -> bool:
        if self._rot_handle_scene_pos is None:
            return False
        dx = pos.x() - self._rot_handle_scene_pos.x()
        dy = pos.y() - self._rot_handle_scene_pos.y()
        return math.hypot(dx, dy) <= _ROT_HANDLE_R + 8

    def _enter_rotate_mode(self, pos: QPointF, center_scene: QPointF, view):
        self._drag_mode = 'rotate'
        self._rot_center_scene = center_scene
        self._rot_start_angle = math.atan2(pos.y() - center_scene.y(),
                                           pos.x() - center_scene.x())
        zoom = view.zoom()
        offset = view._page_offsets.get(view.current_page(), QPointF(0, 0))
        self._rot_center_fitz = fitz.Point(
            (center_scene.x() - offset.x()) / zoom,
            (center_scene.y() - offset.y()) / zoom,
        )
        if self._sel_pending:
            self._pending_snapshot = self._sel_pending.geometry_snapshot()

    def on_press(self, pos: QPointF, event: QMouseEvent, view):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # 회전 핸들 클릭 체크 (선택 중인 어노테이션이 있을 때)
        if self._is_on_rot_handle(pos) and (self._sel_pending is not None or self._sel_xref is not None):
            self._drag_start = pos
            self._was_dragging = False
            # 선택 박스 중심
            if self._sel_item_alive():
                try:
                    center = self._sel_item.rect().center()
                except RuntimeError:
                    center = pos
            else:
                center = pos
            self._enter_rotate_mode(pos, center, view)
            view.setDragMode(view.DragMode.NoDrag)
            return

        # 클릭한 씬 위치의 페이지를 이번 조작의 기준 페이지로 고정 (스크롤/양면 보정)
        self._sel_page = view.page_at_scene(pos)
        fitz_pt = scene_to_fitz_pt(pos, view.zoom(), self._offset(view))
        pending = self._find_pending(pos, view)
        if pending is not None:
            self._sel_page = pending.page_index
            self._sel_pending = pending
            self._sel_xref = None
            self._sel_rect = None
            self._drag_start = pos
            self._was_dragging = False
            scene_rect = self._pending_scene_rect(pending, view)
            if self._uses_scene_pending_rect(pending):
                self._drag_bbox_start = self._scene_rect_to_fitz_rect(scene_rect, view)
            elif pending.annot_type in self._RECT_GEOMETRY_TYPES:
                # 사각형 타입: padding 없는 정확한 rect로 크기조절
                self._drag_bbox_start = _pending_geometry_rect(pending) or pending.bounding_fitz_rect()
            else:
                self._drag_bbox_start = pending.bounding_fitz_rect()
            self._pending_snapshot = pending.geometry_snapshot()
            self._resize_handle = self._pending_resize_handle_at(fitz_pt, pending, self._drag_bbox_start)
            self._drag_mode = 'resize' if self._resize_handle else 'move'
            if scene_rect is not None:
                self._draw_sel_item(scene_rect, view)
            view.setDragMode(view.DragMode.NoDrag)
            return

        annot = self._find_annot(pos, view)
        if annot is not None:
            self._sel_page = view.page_at_scene(pos)
            try:
                atype = annot.type[0]
            except Exception:
                return
            if atype == 13:
                try:
                    fitz_doc = view.doc().fitz_doc()
                    name_raw = fitz_doc.xref_get_key(annot.xref, 'Name')[1]
                    stamp_name = name_raw.lstrip('/')
                except Exception:
                    stamp_name = 'Draft'
                from tools.stamp_tool import STAMP_NAMES
                self._sel_stamp_index = STAMP_NAMES.index(stamp_name) if stamp_name in STAMP_NAMES else 0
            else:
                self._sel_stamp_index = -1
            self._sel_pending = None
            self._sel_xref = annot.xref
            self._sel_rect = annot.rect
            self._drag_start = pos
            self._was_dragging = False
            self._drag_mode = 'move'
            self._resize_handle = None
            self._accum_delta = QPointF(0, 0)
            self._draw_sel_item(annot.rect, view)
            view.setDragMode(view.DragMode.NoDrag)
            if atype in (_ANNOT_TEXT, _ANNOT_FREE_TEXT):
                content = annot.info.get('content', '')
                if content:
                    vp = view.mapFromScene(pos)
                    QToolTip.showText(view.mapToGlobal(vp.toPoint()), content, view)
            return

        self._sel_pending = None
        self._sel_xref = None
        self._sel_rect = None
        self._drag_mode = 'move'
        self._resize_handle = None
        self._drag_bbox_start = None
        self._pending_snapshot = None
        self._remove_sel_item(view)
        view.setDragMode(view.DragMode.ScrollHandDrag)

    def on_move(self, pos: QPointF, event: QMouseEvent, view):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            # 회전 핸들 위에 있으면 회전 커서
            if self._is_on_rot_handle(pos) and (self._sel_pending is not None or self._sel_xref is not None):
                view.viewport().setCursor(QCursor(Qt.CursorShape.CrossCursor))
                self._show_hover_tooltip(pos, event, view)
                return
            # 호버: 커서 위치의 페이지 기준으로 좌표 보정
            if self._sel_pending is None and self._sel_xref is None:
                self._sel_page = view.page_at_scene(pos)
            fitz_pt = scene_to_fitz_pt(pos, view.zoom(), self._offset(view))
            pending = self._find_pending(pos, view)
            annot = None if pending is not None else self._find_annot(pos, view)
            if pending is not None:
                if self._uses_scene_pending_rect(pending):
                    handle_rect = self._scene_rect_to_fitz_rect(self._pending_scene_rect(pending, view), view)
                elif pending.annot_type in self._RECT_GEOMETRY_TYPES:
                    handle_rect = _pending_geometry_rect(pending) or pending.bounding_fitz_rect()
                else:
                    handle_rect = pending.bounding_fitz_rect()
                handle = self._pending_resize_handle_at(fitz_pt, pending, handle_rect)
                view.viewport().setCursor(QCursor(self._cursor_for_handle(handle)))
            elif annot is not None:
                view.viewport().setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            else:
                view.viewport().unsetCursor()
            self._show_hover_tooltip(pos, event, view)
            return

        if self._drag_start is None:
            return
        delta = pos - self._drag_start
        if abs(delta.x()) > 2 or abs(delta.y()) > 2:
            self._was_dragging = True
        if not self._was_dragging:
            return

        if self._sel_pending is not None and self._drag_mode == 'rotate':
            if self._pending_snapshot and self._rot_center_fitz and self._rot_center_scene:
                cx = self._rot_center_scene.x()
                cy = self._rot_center_scene.y()
                current_angle = math.atan2(pos.y() - cy, pos.x() - cx)
                delta_angle = current_angle - self._rot_start_angle
                self._sel_pending.rotate_from_snapshot(
                    self._pending_snapshot,
                    self._rot_center_fitz.x, self._rot_center_fitz.y, delta_angle)
                view.rebuild_pending_item(self._sel_pending)
                scene_rect = self._pending_scene_rect(self._sel_pending, view)
                if scene_rect is not None:
                    self._draw_sel_item(scene_rect, view)
            return

        if self._sel_pending is not None:
            if self._drag_mode == 'resize' and self._resize_handle and self._drag_bbox_start and self._pending_snapshot:
                fitz_pt = scene_to_fitz_pt(pos, view.zoom(), self._offset(view))
                if self._resize_handle in ('p1', 'p2'):
                    snap_p1 = self._pending_snapshot.get('p1')
                    snap_p2 = self._pending_snapshot.get('p2')
                    if self._resize_handle == 'p1':
                        self._sel_pending.p1 = fitz.Point(fitz_pt.x, fitz_pt.y)
                        if snap_p2 is not None:
                            self._sel_pending.p2 = fitz.Point(snap_p2.x, snap_p2.y)
                    else:
                        if snap_p1 is not None:
                            self._sel_pending.p1 = fitz.Point(snap_p1.x, snap_p1.y)
                        self._sel_pending.p2 = fitz.Point(fitz_pt.x, fitz_pt.y)
                else:
                    new_rect = self._resize_rect_from_handle(self._drag_bbox_start, self._resize_handle, fitz_pt)
                    self._sel_pending.resize_from_snapshot(self._pending_snapshot, self._drag_bbox_start, new_rect)
                view.rebuild_pending_item(self._sel_pending)
                scene_rect = self._pending_scene_rect(self._sel_pending, view)
                if scene_rect is not None:
                    self._draw_sel_item(scene_rect, view)
                return

            dx_scene = delta.x()
            dy_scene = delta.y()
            zoom = view.zoom()
            if self._sel_pending.q_item is not None:
                if not self._is_qt_valid(self._sel_pending.q_item):
                    self._sel_pending.q_item = None
                else:
                    try:
                        self._sel_pending.q_item.moveBy(dx_scene, dy_scene)
                    except RuntimeError:
                        self._sel_pending.q_item = None
            self._sel_pending.move(dx_scene / zoom, dy_scene / zoom)
            self._shift_sel_items(dx_scene, dy_scene)
            self._drag_start = pos
            return

        if self._sel_xref is not None and self._sel_rect is not None:
            # 프레임을 매번 재생성하지 않고 누적 이동량만큼 밀어 부드럽게
            shift = delta - self._accum_delta
            self._shift_sel_items(shift.x(), shift.y())
            self._accum_delta = delta

    def on_release(self, pos: QPointF, event: QMouseEvent, view):
        was_dragging = self._was_dragging
        self._was_dragging = False
        view.setDragMode(view.DragMode.ScrollHandDrag)

        if self._sel_pending is not None:
            prev_mode = self._drag_mode
            self._drag_start = None
            self._drag_bbox_start = None
            self._pending_snapshot = None
            self._resize_handle = None
            self._drag_mode = 'move'
            if prev_mode == 'rotate':
                # 회전 완료 후 선택 박스 갱신
                scene_rect = self._pending_scene_rect(self._sel_pending, view)
                if scene_rect is not None:
                    self._draw_sel_item(scene_rect, view)
            return

        if self._sel_xref is None:
            self._drag_start = None
            return

        if was_dragging and self._sel_rect is not None and self._drag_start is not None:
            if self._sel_item_alive():
                zoom = view.zoom()
                orig = self._sel_rect
                dxf = self._accum_delta.x() / zoom
                dyf = self._accum_delta.y() / zoom
                new_rect = fitz.Rect(orig.x0 + dxf, orig.y0 + dyf,
                                     orig.x1 + dxf, orig.y1 + dyf)
                page = view.doc().fitz_page(self._page(view))
                dx = new_rect.x0 - orig.x0
                dy = new_rect.y0 - orig.y0
                annots_to_move = [annot for annot in list(page.annots()) if annot.xref == self._sel_xref]
                for annot in annots_to_move:
                    try:
                        saved_xref = annot.xref
                        atype = annot.type[0]
                        if atype == _ANNOT_INK:
                            new_annot = _move_ink_annot(page, annot, dx, dy)
                            if new_annot and saved_xref == self._sel_xref:
                                self._sel_xref = new_annot.xref
                        elif atype == 13:
                            from tools.stamp_tool import STAMP_NAMES, _stamp_idx
                            idx = self._sel_stamp_index
                            name = STAMP_NAMES[idx] if 0 <= idx < len(STAMP_NAMES) else 'Draft'
                            page.delete_annot(annot)
                            new_annot = page.add_stamp_annot(new_rect, stamp=_stamp_idx(name))
                            if new_annot:
                                new_annot.update()
                                self._sel_xref = new_annot.xref
                        else:
                            annot.set_rect(new_rect)
                            annot.update()
                        view.doc().mark_dirty()
                    except Exception as exc:
                        print(f'[SelectTool] move error: {exc}')
                self._sel_rect = new_rect

            self._remove_sel_item(view)
            view._renderer.invalidate(self._page(view))
            view.refresh_page()
            if self._sel_rect is not None:
                self._draw_sel_item(self._sel_rect, view)

        self._drag_start = None

    def _show_hover_tooltip(self, pos: QPointF, event: QMouseEvent, view):
        if not view.doc().is_open:
            QToolTip.hideText()
            return
        page_idx, fitz_pt = resolve_page_and_fitz_pt(view, pos)
        try:
            page = view.doc().fitz_page(page_idx)
        except Exception:
            QToolTip.hideText()
            return
        for annot in list(page.annots()):
            try:
                atype = annot.type[0]
            except Exception:
                continue
            if atype not in (_ANNOT_TEXT, _ANNOT_FREE_TEXT):
                continue
            rect = annot.rect
            if rect.x0 - _TOLERANCE <= fitz_pt.x <= rect.x1 + _TOLERANCE and rect.y0 - _TOLERANCE <= fitz_pt.y <= rect.y1 + _TOLERANCE:
                content = annot.info.get('content', '')
                if content:
                    vp = view.mapFromScene(pos)
                    QToolTip.showText(view.mapToGlobal(vp.toPoint()), content, view)
                    return
        QToolTip.hideText()

    def edit_pending(self, pending: PendingAnnotation, view) -> bool:
        """미확정 메모/텍스트 내용을 더블클릭으로 편집. 빈 내용이면 삭제."""
        if pending.annot_type not in ('text', 'direct_text', 'freetext'):
            return False
        title = '메모 편집' if pending.annot_type == 'text' else '텍스트 편집'
        new_text, ok = QInputDialog.getMultiLineText(view, title, '내용 입력:', pending.text)
        if not ok:
            return True
        if not new_text.strip():
            pending.remove_from_scene()
            view.pending_layer().remove_uid(pending.uid)
            if self._sel_pending is pending:
                self._sel_pending = None
                self._remove_sel_item(view)
            view.notify_pending_changed()
            return True
        pending.text = new_text
        view.rebuild_pending_item(pending)
        view.doc().mark_dirty()
        if self._sel_pending is pending:
            scene_rect = self._pending_scene_rect(pending, view)
            if scene_rect is not None:
                self._draw_sel_item(scene_rect, view)
        return True

    def on_double_click(self, pos: QPointF, event: QMouseEvent, view) -> bool:
        self._sel_page = view.page_at_scene(pos)
        pending = self._find_pending(pos, view)
        if pending is not None:
            self._sel_page = pending.page_index
            if self.edit_pending(pending, view):
                return True
        annot = self._find_annot(pos, view)
        if annot is None:
            return False
        self._sel_page = view.page_at_scene(pos)
        try:
            atype = annot.type[0]
        except Exception:
            return False
        if atype not in (_ANNOT_TEXT, _ANNOT_FREE_TEXT):
            return False
        current = annot.info.get('content', '')
        title = '메모 편집' if atype == _ANNOT_TEXT else '텍스트 편집'
        new_text, ok = QInputDialog.getMultiLineText(view, title, '내용 입력:', current)
        if not ok:
            return True
        try:
            if new_text.strip():
                annot.set_info(content=new_text)
            else:
                page = view.doc().fitz_page(self._page(view))
                for item in list(page.annots()):
                    if item.xref == annot.xref:
                        page.delete_annot(item)
                        break
                self._sel_xref = None
                self._sel_rect = None
                self._sel_item = None
                view.doc().mark_dirty()
                view._renderer.invalidate(self._page(view))
                view.refresh_page()
                return True
            annot.update()
            view.doc().mark_dirty()
        except Exception as exc:
            print(f'[SelectTool] edit error: {exc}')
        self._sel_item = None
        view._renderer.invalidate(self._page(view))
        view.refresh_page()
        if self._sel_rect is not None:
            self._draw_sel_item(self._sel_rect, view)
        return True

    def on_key(self, event: QKeyEvent, view) -> bool:
        if event.key() not in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            return False
        if self._sel_pending is not None:
            self._sel_pending.remove_from_scene()
            view.pending_layer().remove_uid(self._sel_pending.uid)
            self._sel_pending = None
            self._remove_sel_item(view)
            view.notify_pending_changed()
            return True
        if self._sel_xref is not None and view.doc().is_open:
            page = view.doc().fitz_page(self._page(view))
            for annot in list(page.annots()):
                if annot.xref == self._sel_xref:
                    try:
                        page.delete_annot(annot)
                        view.doc().mark_dirty()
                    except Exception as exc:
                        print(f'[SelectTool] delete error: {exc}')
                    break
            self._sel_xref = None
            self._sel_rect = None
            self._sel_item = None
            view._renderer.invalidate(self._page(view))
            view.refresh_page()
            return True
        return False


class ExistingSelectionDelegate:
    """메모/텍스트 같은 '생성 도구'에서 이미 놓인 어노테이션을 클릭했을 때
    새로 만들지 않고 선택·이동·크기조절·편집·삭제하도록 SelectTool 동작을
    위임하는 헬퍼. 빈 곳을 클릭했을 때만 생성 로직이 이어진다."""

    def __init__(self):
        self.sel = SelectTool()
        self.active = False            # 현재 드래그가 위임 중인가
        self._deselect_click = False   # 이번 클릭이 '선택 해제'만 하는 클릭인가

    def _hit(self, pos: QPointF, view) -> bool:
        if self.sel._is_on_rot_handle(pos) and (
                self.sel._sel_pending is not None or self.sel._sel_xref is not None):
            return True
        if self.sel._find_pending(pos, view) is not None:
            return True
        return self.sel._find_annot(pos, view) is not None

    def press(self, pos: QPointF, event: QMouseEvent, view) -> bool:
        """True 반환 시 이벤트를 소비했으므로 생성 로직을 건너뛴다."""
        if not view.doc().is_open:
            return False
        if self._hit(pos, view):
            self.active = True
            self.sel.on_press(pos, event, view)
            return True
        # 빈 곳 클릭: 선택돼 있던 게 있으면 이번 클릭은 '해제'로만 소비
        if self.sel._sel_pending is not None or self.sel._sel_xref is not None:
            self.sel._sel_pending = None
            self.sel._sel_xref = None
            self.sel._sel_rect = None
            self.sel._remove_sel_item(view)
            self._deselect_click = True
            return True
        return False

    def move(self, pos: QPointF, event: QMouseEvent, view):
        if self.active and (event.buttons() & Qt.MouseButton.LeftButton):
            self.sel.on_move(pos, event, view)
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            # 호버 시 이동/크기조절 커서 표시
            self.sel.on_move(pos, event, view)

    def release(self, pos: QPointF, event: QMouseEvent, view) -> bool:
        """True 반환 시 생성 로직을 건너뛴다."""
        if self._deselect_click:
            self._deselect_click = False
            return True
        if self.active:
            self.sel.on_release(pos, event, view)
            self.active = False
            view.setDragMode(view.DragMode.NoDrag)   # 생성 도구는 NoDrag 유지
            return True
        return False

    def find_pending_at(self, pos: QPointF, view) -> PendingAnnotation | None:
        return self.sel._find_pending(pos, view)

    def refresh_selection_box(self, pending: PendingAnnotation, view):
        self.sel._sel_pending = pending
        self.sel._sel_page = pending.page_index
        scene_rect = self.sel._pending_scene_rect(pending, view)
        if scene_rect is not None:
            self.sel._draw_sel_item(scene_rect, view)

    def double_click(self, pos: QPointF, event: QMouseEvent, view) -> bool:
        return self.sel.on_double_click(pos, event, view)

    def key(self, event: QKeyEvent, view) -> bool:
        return self.sel.on_key(event, view)

    def deactivate(self, view):
        self.sel.deactivate(view)
        self.active = False
        self._deselect_click = False
