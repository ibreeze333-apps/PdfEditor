from __future__ import annotations

import math

import fitz
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsPathItem

from tools.base_tool import BaseTool
from utils.annot_mapper import resolve_page_and_fitz_pt
from utils.annot_style import scene_dashes, scene_width, tool_style
from utils.pending_layer import PendingAnnotation
from utils.errlog import swallowed

_ERASER_RADIUS = 10
_FITZ_INK_TYPE = 14  # PDF_ANNOT_INK


def _norm_pts(stroke) -> list[tuple[float, float]]:
    """stroke 점 목록을 (x, y) 튜플 리스트로 정규화."""
    result = []
    for pt in stroke:
        if hasattr(pt, 'x'):
            result.append((pt.x, pt.y))
        else:
            result.append((float(pt[0]), float(pt[1])))
    return result


def _resample_stroke_pts(pts: list[tuple], step: float) -> list[tuple]:
    """stroke 점을 step 간격으로 재샘플링."""
    if len(pts) < 2:
        return list(pts)
    result = [pts[0]]
    carry = 0.0
    for i in range(1, len(pts)):
        p0, p1 = pts[i - 1], pts[i]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-6:
            continue
        ux, uy = dx / seg_len, dy / seg_len
        d = step - carry
        while d < seg_len:
            result.append((p0[0] + ux * d, p0[1] + uy * d))
            d += step
        carry = max(0.0, d - seg_len)
    result.append(pts[-1])
    return result


def _hits_stroke(strokes: list, fx: float, fy: float, radius: float) -> bool:
    """stroke 목록 중 (fx, fy)에서 radius 이내에 점/선분이 있는지 검사."""
    r2 = radius * radius
    for stroke in strokes:
        pts = _norm_pts(stroke)
        for i, (x, y) in enumerate(pts):
            if (x - fx) ** 2 + (y - fy) ** 2 <= r2:
                return True
            if i > 0:
                px, py = pts[i - 1]
                dx, dy = x - px, y - py
                seg2 = dx * dx + dy * dy
                if seg2 > 0:
                    t = max(0.0, min(1.0, ((fx - px) * dx + (fy - py) * dy) / seg2))
                    cx, cy = px + t * dx, py + t * dy
                    if (cx - fx) ** 2 + (cy - fy) ** 2 <= r2:
                        return True
    return False


def _erode_strokes(strokes: list, fx: float, fy: float, radius: float) -> list[list[tuple]]:
    """지우개 원 안에 있는 구간만 제거하고 살아남은 sub-stroke 목록 반환."""
    r2 = radius * radius
    result = []
    for stroke in strokes:
        norm = _norm_pts(stroke)
        # 정밀한 교차 검출을 위해 밀도 높게 재샘플링
        dense = _resample_stroke_pts(norm, step=max(0.5, radius * 0.3))
        current: list[tuple] = []
        for pt in dense:
            if (pt[0] - fx) ** 2 + (pt[1] - fy) ** 2 <= r2:
                if len(current) >= 1:
                    result.append(current)
                current = []
            else:
                current.append(pt)
        if len(current) >= 1:
            result.append(current)
    return result


def _resample_points(points: list[QPointF], step: float = 4.0) -> list[QPointF]:
    if len(points) < 2:
        return list(points)
    sampled = [QPointF(points[0])]
    carry = 0.0
    for start, end in zip(points, points[1:]):
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-6:
            continue
        ux, uy = dx / seg_len, dy / seg_len
        dist = step - carry
        while dist < seg_len:
            sampled.append(QPointF(start.x() + ux * dist, start.y() + uy * dist))
            dist += step
        carry = max(0.0, dist - seg_len)
    if sampled[-1] != points[-1]:
        sampled.append(QPointF(points[-1]))
    return sampled


def _make_wavy_points(points: list[QPointF], amplitude: float = 4.0, wavelength: float = 22.0) -> list[QPointF]:
    base = _resample_points(points, step=max(3.0, wavelength / 5.0))
    if len(base) < 2:
        return base
    result: list[QPointF] = []
    distance = 0.0
    prev = base[0]
    for index, point in enumerate(base):
        if index > 0:
            distance += math.hypot(point.x() - prev.x(), point.y() - prev.y())
        prev_pt = base[index - 1] if index > 0 else point
        next_pt = base[index + 1] if index + 1 < len(base) else point
        dx = next_pt.x() - prev_pt.x()
        dy = next_pt.y() - prev_pt.y()
        length = math.hypot(dx, dy)
        if length < 1e-6:
            result.append(QPointF(point))
            prev = point
            continue
        nx, ny = -dy / length, dx / length
        offset = amplitude * math.sin((distance / wavelength) * 2 * math.pi)
        result.append(QPointF(point.x() + nx * offset, point.y() + ny * offset))
        prev = point
    return result


def _catmull_rom(points: list[QPointF], samples_per_seg: int = 8) -> list[QPointF]:
    """점들을 지나는 Catmull-Rom 곡선을 촘촘한 점으로 풀어낸다.

    마우스는 빠르게 그으면 수십 px 씩 건너뛰며 좌표를 준다. 코너만 깎는
    방식(Chaikin)은 그 사이를 여전히 직선으로 이어서 '자로 그은 것처럼'
    딱딱 끊겨 보인다. 여기서는 점 사이를 실제 곡선으로 채워 넣는다.
    """
    n = len(points)
    if n < 3:
        return list(points)
    out: list[QPointF] = [points[0]]
    for i in range(n - 1):
        p0 = points[i - 1] if i > 0 else points[i]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[i + 2] if i + 2 < n else points[i + 1]
        for s in range(1, samples_per_seg + 1):
            t = s / samples_per_seg
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1.x()) +
                       (-p0.x() + p2.x()) * t +
                       (2 * p0.x() - 5 * p1.x() + 4 * p2.x() - p3.x()) * t2 +
                       (-p0.x() + 3 * p1.x() - 3 * p2.x() + p3.x()) * t3)
            y = 0.5 * ((2 * p1.y()) +
                       (-p0.y() + p2.y()) * t +
                       (2 * p0.y() - 5 * p1.y() + 4 * p2.y() - p3.y()) * t2 +
                       (-p0.y() + 3 * p1.y() - 3 * p2.y() + p3.y()) * t3)
            out.append(QPointF(x, y))
    return out


def _dedupe_points(points: list[QPointF], min_dist: float = 1.5) -> list[QPointF]:
    """너무 붙어 있는 점을 걸러낸다 (손떨림·중복 이벤트 제거).

    끝점은 반드시 남긴다 — 획이 짧아지면 안 되기 때문.
    """
    if len(points) < 3:
        return list(points)
    out = [points[0]]
    d2 = min_dist * min_dist
    for p in points[1:-1]:
        last = out[-1]
        if (p.x() - last.x()) ** 2 + (p.y() - last.y()) ** 2 >= d2:
            out.append(p)
    out.append(points[-1])
    return out


def _smooth_points(points: list[QPointF], iterations: int = 2) -> list[QPointF]:
    """마우스 좌표의 각진 꺾임을 없앤다 (Chaikin 코너 컷팅).

    마우스 이벤트는 띄엄띄엄 들어와서 그대로 이으면 폴리라인이 울퉁불퉁해
    보인다. 각 선분을 1/4·3/4 지점으로 잘라 반복하면 곡선에 수렴한다.
    양 끝점은 그대로 두어 획의 시작·끝 위치가 밀리지 않게 한다.
    PDF ink 어노테이션도 결국 점을 직선으로 잇기 때문에, 미리보기만이 아니라
    저장되는 점 목록 자체를 다듬어야 한다.
    """
    pts = list(points)
    if len(pts) < 3:
        return pts
    for _ in range(max(0, iterations)):
        if len(pts) < 3:
            break
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            out.append(QPointF(a.x() * 0.75 + b.x() * 0.25,
                               a.y() * 0.75 + b.y() * 0.25))
            out.append(QPointF(a.x() * 0.25 + b.x() * 0.75,
                               a.y() * 0.25 + b.y() * 0.75))
        out.append(pts[-1])
        pts = out
    return pts


def _path_from_points(points: list[QPointF]) -> QPainterPath:
    """점 목록 → 부드러운 경로 (중점 이차 베지어)."""
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(points[0])
    if len(points) < 3:
        for point in points[1:]:
            path.lineTo(point)
        return path
    # 각 점을 제어점으로, 이웃 두 점의 중점을 통과점으로 삼는다.
    for prev, cur in zip(points[1:-1], points[2:]):
        mid = QPointF((prev.x() + cur.x()) / 2.0, (prev.y() + cur.y()) / 2.0)
        path.quadTo(prev, mid)
    path.lineTo(points[-1])
    return path


class PencilTool(BaseTool):
    name = 'pencil'
    label = '✏ 필기'
    cursor = Qt.CursorShape.CrossCursor
    shortcut = 'P'

    def __init__(self):
        self._points: list[QPointF] = []
        self._preview: QGraphicsPathItem | None = None
        self._eraser_mode: bool = False
        self._eraser_cursor: QGraphicsEllipseItem | None = None

    @property
    def eraser_mode(self) -> bool:
        return self._eraser_mode

    @eraser_mode.setter
    def eraser_mode(self, val: bool):
        self._eraser_mode = val

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def deactivate(self, view):
        self._remove_eraser_cursor(view)
        super().deactivate(view)

    def _cursor_alive(self) -> bool:
        if self._eraser_cursor is None:
            return False
        try:
            self._eraser_cursor.scene()
            return True
        except RuntimeError:
            self._eraser_cursor = None
            return False

    def _remove_eraser_cursor(self, view):
        if not self._cursor_alive():
            self._eraser_cursor = None
            return
        try:
            scene = self._eraser_cursor.scene()
            if scene is not None:
                scene.removeItem(self._eraser_cursor)
        except Exception:
            swallowed()
        self._eraser_cursor = None

    def _update_eraser_cursor(self, pos: QPointF, view):
        if not self._cursor_alive():
            self._eraser_cursor = None
        if self._eraser_cursor is None:
            size = _ERASER_RADIUS * view.zoom()
            item = QGraphicsEllipseItem(-size, -size, size * 2, size * 2)
            item.setPen(QPen(QColor(200, 50, 50), 1.5, Qt.PenStyle.DashLine))
            item.setZValue(200)
            view.scene().addItem(item)
            self._eraser_cursor = item
        try:
            size = _ERASER_RADIUS * view.zoom()
            self._eraser_cursor.setRect(-size, -size, size * 2, size * 2)
            self._eraser_cursor.setPos(pos)
        except RuntimeError:
            self._eraser_cursor = None

    def _erase_at(self, pos: QPointF, view):
        if not view.doc().is_open:
            return
        page_idx, fitz_pt = resolve_page_and_fitz_pt(view, pos)
        fx, fy = fitz_pt.x, fitz_pt.y
        layer = view.pending_layer()
        pending_changed = False

        # ── pending ink: 닿은 구간만 제거, 나머지는 분리된 stroke로 유지 ──
        for pa in list(layer.for_page(page_idx)):
            if pa.annot_type != 'ink' or not pa.points:
                continue
            if not _hits_stroke(pa.points, fx, fy, _ERASER_RADIUS):
                continue
            surviving = _erode_strokes(pa.points, fx, fy, _ERASER_RADIUS)
            pa.remove_from_scene()
            layer.remove_uid(pa.uid)
            for sub in surviving:
                new_pa = PendingAnnotation(
                    uid=layer.next_uid(),
                    page_index=pa.page_index,
                    tool_name=pa.tool_name,
                    annot_type='ink',
                    points=[sub],
                    stroke_color=pa.stroke_color,
                    border_width=pa.border_width,
                    dashes=pa.dashes,
                )
                layer.add(new_pa)
                view.rebuild_pending_item(new_pa)
            pending_changed = True

        if pending_changed:
            view.notify_pending_changed()

        # ── committed ink: 닿은 구간만 제거, 나머지는 새 annot으로 다시 추가 ──
        page = view.doc().fitz_page(page_idx)
        fitz_changed = False
        for annot in list(page.annots()):
            if annot.type[0] != _FITZ_INK_TYPE:
                continue
            strokes = [_norm_pts(s) for s in (annot.vertices or [])]
            if not _hits_stroke(strokes, fx, fy, _ERASER_RADIUS):
                continue
            stroke_color = annot.colors.get('stroke')
            border_width = annot.border.get('width', 1.0)
            border_dashes = annot.border.get('dashes')
            surviving = _erode_strokes(strokes, fx, fy, _ERASER_RADIUS)
            page.delete_annot(annot)
            for sub in surviving:
                new_annot = page.add_ink_annot([sub])
                if stroke_color:
                    new_annot.set_colors(stroke=stroke_color)
                new_annot.set_border(width=border_width, dashes=border_dashes)
                new_annot.update()
            fitz_changed = True

        if fitz_changed:
            view.doc().mark_dirty()
            self._eraser_cursor = None
            view.refresh_page()

    def on_press(self, pos, event, view):
        if self._eraser_mode:
            self._erase_at(pos, view)
            return
        self._points = [pos]
        style = tool_style(self.name)
        pen = QPen(style.color, scene_width(style.width, view), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        if style.dashes and not style.is_wavy():
            pen.setDashPattern(scene_dashes(style.dashes, style.width))
        item = QGraphicsPathItem()
        item.setPen(pen)
        item.setZValue(10)
        view.scene().addItem(item)
        self._preview = item

    def _render_points(self) -> list[QPointF]:
        """화면·PDF 에 함께 쓰는 최종 점 목록.

        미리보기와 커밋이 같은 목록을 쓰므로 '그릴 때와 적용 후 모양이 다른'
        일이 생기지 않는다.
        """
        style = tool_style(self.name)
        if style.is_wavy():
            return _make_wavy_points(self._points,
                                     amplitude=max(4.0, style.width * 1.4),
                                     wavelength=max(18.0, style.width * 7.0))
        # 마우스 좌표를 그대로 이으면 자로 그은 것처럼 딱딱 끊겨 보인다.
        # ① 너무 붙은 점 제거(미세 떨림) → ② 코너 깎기 → ③ 점 사이를 곡선으로
        # 채우기 → ④ PDF 에 넣을 만큼만 남기기.
        # 이동평균도 써 봤지만 부드러움은 비슷한데 획이 그은 자리에서 4배쯤
        # 밀려서 뺐다 (이탈 0.9pt vs 3.5pt).
        base = _dedupe_points(self._points, min_dist=3.0)
        if len(base) < 3:
            return base
        curved = _catmull_rom(_smooth_points(base, iterations=2), samples_per_seg=8)
        return _resample_points(curved, step=2.0)

    def on_move(self, pos, event, view):
        if self._eraser_mode:
            self._update_eraser_cursor(pos, view)
            if event.buttons() & Qt.MouseButton.LeftButton:
                self._erase_at(pos, view)
            return
        if not self._preview:
            return
        self._points.append(pos)
        self._preview.setPath(_path_from_points(self._render_points()))

    def on_release(self, pos, event, view):
        if self._eraser_mode:
            return
        preview = self._preview
        self._preview = None
        if len(self._points) >= 2:
            style = tool_style(self.name)
            render_points = self._render_points()
            zoom = view.zoom()
            page_idx = view.page_at_scene(self._points[0])
            offset = view.page_offset(page_idx)
            fitz_points = [((p.x() - offset.x()) / zoom, (p.y() - offset.y()) / zoom) for p in render_points]
            pending = PendingAnnotation(
                uid=view.pending_layer().next_uid(),
                page_index=page_idx,
                tool_name=self.name,
                annot_type='ink',
                points=[fitz_points],
                stroke_color=style.fitz_color(),
                border_width=max(0.5, style.width),
                dashes=style.dashes if (style.dashes and not style.is_wavy()) else None,
                q_item=preview,
            )
            view.pending_layer().add(pending)
            view.doc().mark_dirty()
            view.notify_pending_changed()
        elif preview:
            view.scene().removeItem(preview)
        self._points = []
