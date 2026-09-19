from __future__ import annotations

import math

import fitz
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItemGroup, QGraphicsLineItem, QGraphicsPathItem

from tools.base_tool import BaseTool
from utils.annot_mapper import resolve_page_and_fitz_pt, scene_to_fitz_pt
from utils.annot_style import scene_dashes, scene_width, tool_style
from utils.pending_layer import PendingAnnotation


# PDF 선 어노테이션의 화살촉(/LE)은 뷰어가 선 굵기에 비례해 그린다.
# MuPDF 렌더 실측: 길이 ≈ 10.25 × 선굵기, 반폭 ≈ 5.25 × 선굵기.
# 미리보기를 이 비율로 맞춰야 'PDF에 적용' 후 화살촉만 커지지 않는다.
_PDF_ARROW_LEN_RATIO = 10.25
_PDF_ARROW_ANGLE     = 0.474   # atan(5.25 / 10.25) rad


def _line_arrow_pts(x1: float, y1: float, x2: float, y2: float,
                    width: float, scale: float = 1.0,
                    double: bool = False) -> list[tuple[float, float]]:
    """선 화살표를 폴리곤 하나로 만든다 — 얇은 몸통 + 적당한 화살촉.

    PDF 의 /LE 화살촉은 크기를 지정할 수 없고 뷰어가 선 굵기에 비례해
    그리는데, MuPDF 는 길이 10.25×굵기로 매우 크게 그린다. 굵기 1.5 만
    넘어도 화살촉이 감당 못 하게 커지는 이유다.
    그래서 화살촉을 우리가 직접 그린다 — 크기를 우리가 정하고, 뷰어마다
    다르게 보이지도 않는다.
    """
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 2.0:
        return []
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux

    w = float(width)
    shaft_half = scale * max(w / 2.0, 0.35)
    head_len   = scale * max(9.0, w * 3.2)
    head_half  = scale * max(4.5, w * 1.9)
    # 화살촉이 선보다 길어지지 않게 (짧은 화살표에서 머리만 남는 것 방지)
    max_head = length * (0.42 if double else 0.55)
    if head_len > max_head:
        ratio = max_head / head_len
        head_len *= ratio
        head_half *= ratio

    bx, by = x2 - ux * head_len, y2 - uy * head_len
    if not double:
        return [
            (x1 + nx * shaft_half, y1 + ny * shaft_half),
            (bx + nx * shaft_half, by + ny * shaft_half),
            (bx + nx * head_half,  by + ny * head_half),
            (x2, y2),
            (bx - nx * head_half,  by - ny * head_half),
            (bx - nx * shaft_half, by - ny * shaft_half),
            (x1 - nx * shaft_half, y1 - ny * shaft_half),
        ]
    ax, ay = x1 + ux * head_len, y1 + uy * head_len
    return [
        (x1, y1),
        (ax + nx * head_half,  ay + ny * head_half),
        (ax + nx * shaft_half, ay + ny * shaft_half),
        (bx + nx * shaft_half, by + ny * shaft_half),
        (bx + nx * head_half,  by + ny * head_half),
        (x2, y2),
        (bx - nx * head_half,  by - ny * head_half),
        (bx - nx * shaft_half, by - ny * shaft_half),
        (ax - nx * shaft_half, ay - ny * shaft_half),
        (ax - nx * head_half,  ay - ny * head_half),
    ]


def _arrow_strokes(x1: float, y1: float, x2: float, y2: float,
                   width: float, *, scale: float = 1.0, closed: bool = True,
                   double: bool = False, wavy: bool = False) -> list[list[tuple[float, float]]]:
    """화살표를 [몸통, 화살촉…] 획 목록으로 만든다.

    첫 항목이 몸통(점선·굵기 적용), 나머지가 화살촉이다. 화살촉 크기를
    우리가 정하므로 /LE 처럼 굵기에 따라 폭주하지 않는다.
    closed=True 면 화살촉은 닫힌 삼각형(채움), False 면 열린 ∧ 모양.
    좌표와 width 는 같은 단위여야 한다(scale 은 절대 상수 보정용).
    """
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 2.0:
        return []
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux

    w = float(width)
    head_len  = scale * max(9.0, w * 3.2)
    head_half = scale * max(4.5, w * 1.9)
    max_head = length * (0.42 if double else 0.55)
    if head_len > max_head:
        r = max_head / head_len
        head_len *= r
        head_half *= r

    def head_at(tipx, tipy, sx, sy):
        """(sx,sy)→(tip) 방향 화살촉. 밑변 중점과 꼭짓점들을 돌려준다."""
        vx, vy = tipx - sx, tipy - sy
        n = math.hypot(vx, vy) or 1.0
        vx, vy = vx / n, vy / n
        px, py = -vy, vx
        bx, by = tipx - vx * head_len, tipy - vy * head_len
        c1 = (bx + px * head_half, by + py * head_half)
        c2 = (bx - px * head_half, by - py * head_half)
        return (bx, by), c1, c2

    # 몸통은 화살촉 밑변까지만 (화살촉 위로 겹쳐 그리지 않게)
    end_base, e1, e2 = head_at(x2, y2, x1, y1)
    start = (x1, y1)
    heads: list[list[tuple[float, float]]] = []
    if double:
        start_base, s1, s2 = head_at(x1, y1, x2, y2)
        start = start_base
        heads.append([s1, (x1, y1), s2, s1] if closed else [s1, (x1, y1), s2])
    heads.append([e1, (x2, y2), e2, e1] if closed else [e1, (x2, y2), e2])

    if wavy:
        shaft = _wave_points(start[0], start[1], end_base[0], end_base[1],
                             amplitude=max(2.0, w * 0.9) * scale,
                             wavelength=18.0 * scale)
    else:
        shaft = [start, end_base]
    return [shaft] + heads


def _le_head_points(x1: float, y1: float, x2: float, y2: float,
                    width: float) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """PDF 뷰어가 그리는 화살촉과 같은 크기의 꼭짓점 두 개.

    좌표와 width 는 같은 단위여야 한다(둘 다 씬 단위 또는 둘 다 fitz 단위).
    """
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-3:
        return None
    arrow_len = max(4.0, width * _PDF_ARROW_LEN_RATIO)
    angle = _PDF_ARROW_ANGLE
    ux, uy = dx / length, dy / length
    ax1 = x2 - arrow_len * (ux * math.cos(angle) - uy * math.sin(angle))
    ay1 = y2 - arrow_len * (uy * math.cos(angle) + ux * math.sin(angle))
    ax2 = x2 - arrow_len * (ux * math.cos(angle) + uy * math.sin(angle))
    ay2 = y2 - arrow_len * (uy * math.cos(angle) - ux * math.sin(angle))
    return (ax1, ay1), (ax2, ay2)


def _arrow_head_points(x1: float, y1: float, x2: float, y2: float, width: float,
                       scale: float = 1.0) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """직접 그리는(물결 등) 화살촉 꼭짓점.

    scale: 좌표계 배율. 씬 좌표로 미리보기를 그릴 때 view.zoom() 을 넘긴다 —
    화살촉 크기 하한/상한이 절대값이라 배율을 곱하지 않으면 미리보기가
    실제 결과의 1/zoom 크기로 작게 나온다.
    """
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-3:
        return None
    arrow_len = scale * max(12.0, min(28.0, width * 3.8))
    angle = 0.46
    ux, uy = dx / length, dy / length
    ax1 = x2 - arrow_len * (ux * math.cos(angle) - uy * math.sin(angle))
    ay1 = y2 - arrow_len * (uy * math.cos(angle) + ux * math.sin(angle))
    ax2 = x2 - arrow_len * (ux * math.cos(angle) + uy * math.sin(angle))
    ay2 = y2 - arrow_len * (uy * math.cos(angle) - ux * math.sin(angle))
    return (ax1, ay1), (ax2, ay2)


def _wave_points(x1: float, y1: float, x2: float, y2: float,
                 amplitude: float = 3.0,
                 wavelength: float = 18.0) -> list[tuple[float, float]]:
    dx, dy = x2 - x1, y2 - y1
    length = max(1.0, math.hypot(dx, dy))
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    steps = max(10, int(length / 2.5))
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        base_x = x1 + dx * t
        base_y = y1 + dy * t
        offset = amplitude * math.sin((length * t / wavelength) * 2 * math.pi)
        pts.append((base_x + nx * offset, base_y + ny * offset))
    return pts


def _path_from_points(points: list[tuple[float, float]]) -> QPainterPath:
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(*points[0])
    for x, y in points[1:]:
        path.lineTo(x, y)
    return path


def _head_path(x1: float, y1: float, x2: float, y2: float, width: float, closed: bool,
               scale: float = 1.0, pdf_le: bool = False) -> QPainterPath:
    pts = (_le_head_points(x1, y1, x2, y2, width) if pdf_le
           else _arrow_head_points(x1, y1, x2, y2, width, scale))
    if pts is None:
        return QPainterPath()
    (ax1, ay1), (ax2, ay2) = pts
    path = QPainterPath()
    path.moveTo(ax1, ay1)
    path.lineTo(x2, y2)
    path.lineTo(ax2, ay2)
    if closed:
        path.closeSubpath()
    return path


def _shaft_end_point(x1: float, y1: float, x2: float, y2: float, width: float,
                     scale: float = 1.0, pdf_le: bool = False) -> tuple[float, float]:
    pts = (_le_head_points(x1, y1, x2, y2, width) if pdf_le
           else _arrow_head_points(x1, y1, x2, y2, width, scale))
    if pts is None:
        return x2, y2
    (ax1, ay1), (ax2, ay2) = pts
    return (ax1 + ax2) / 2.0, (ay1 + ay2) / 2.0


def _draw_arrow_group(group, x1, y1, x2, y2, style, zoom, double: bool):
    """커밋될 모양 그대로 미리보기를 그린다 (_arrow_strokes 공유)."""
    closed = getattr(style, 'arrow_head', 'closed') != 'open'
    strokes = _arrow_strokes(x1, y1, x2, y2, style.width, scale=zoom,
                             closed=closed, double=double, wavy=style.is_wavy())
    if not strokes:
        return group
    sw = max(0.5, style.width * zoom)

    shaft_pen = QPen(style.color, sw)
    shaft_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    if style.dashes and not style.is_wavy():
        shaft_pen.setDashPattern(scene_dashes(style.dashes, style.width))
    shaft = QGraphicsPathItem(_path_from_points(strokes[0]))
    shaft.setPen(shaft_pen)
    shaft.setBrush(QBrush(Qt.BrushStyle.NoBrush))
    shaft.setParentItem(group)

    filled = getattr(style, 'arrow_fill', 'filled') == 'filled'
    for head in strokes[1:]:
        path = _path_from_points(head)
        item = QGraphicsPathItem(path)
        if closed:
            item.setPen(QPen(style.color, max(0.3, style.width * 0.12 * zoom)))
            item.setBrush(QBrush(style.color if filled else QColor(255, 255, 255)))
        else:
            pen = QPen(style.color, sw)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            item.setPen(pen)
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        item.setParentItem(group)
    return group


def _clear_group(group):
    for child in list(group.childItems()):
        child.setParentItem(None)
        sc = child.scene()
        if sc is not None:
            sc.removeItem(child)


def _emphasized_preview(group, pts, style):
    if pts:
        path = QPainterPath()
        path.moveTo(*pts[0])
        for pt in pts[1:]:
            path.lineTo(*pt)
        path.closeSubpath()
        item = QGraphicsPathItem(path)
        item.setPen(QPen(style.color, 0.5))
        item.setBrush(QBrush(style.color))
        item.setParentItem(group)
    return group


def _build_arrow_preview(group: QGraphicsItemGroup | None,
                         x1: float, y1: float, x2: float, y2: float,
                         style, zoom: float = 1.0):
    if group is None:
        return None
    _clear_group(group)
    if style.is_emphasized():
        return _emphasized_preview(
            group, _block_arrow_pts(x1, y1, x2, y2, style.width, zoom), style)
    return _draw_arrow_group(group, x1, y1, x2, y2, style, zoom, double=False)


def _build_double_arrow_preview(group: QGraphicsItemGroup | None,
                                x1: float, y1: float, x2: float, y2: float,
                                style, zoom: float = 1.0):
    if group is None:
        return None
    _clear_group(group)
    if style.is_emphasized():
        return _emphasized_preview(
            group, _block_double_arrow_pts(x1, y1, x2, y2, style.width, zoom), style)
    return _draw_arrow_group(group, x1, y1, x2, y2, style, zoom, double=True)


def _arrow_fill_color(style):
    if getattr(style, 'arrow_head', 'closed') == 'open':
        return None
    if getattr(style, 'arrow_fill', 'filled') == 'filled':
        return style.fitz_color()
    return [1.0, 1.0, 1.0]


def _fusiform_body_pts(
    x1: float, y1: float, x2: float, y2: float,
    width: float,
    t_start: float = 0.0,
    t_end: float = 1.0,
    n: int = 28,
) -> list[tuple[float, float]]:
    """
    유선형(방추형) 화살축 폴리곤.
    t_start~t_end 범위에서 사인 곡선으로 굵기가 변함 (양 끝 → 0, 중앙 → max).
    Returns 닫힌 폴리곤 [(x,y)...] in FITZ 좌표.
    """
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    if L < 2.0:
        return []
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux  # 왼쪽 수직 방향

    max_half_w = width * 1.5  # 최대 반폭 (fitz 포인트)

    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []
    span = t_end - t_start

    for i in range(n + 1):
        t = t_start + span * i / n
        t_norm = (t - t_start) / span if span > 1e-9 else 0.0
        half_w = max_half_w * math.sin(math.pi * t_norm)
        cx = x1 + t * L * ux
        cy = y1 + t * L * uy
        upper.append((cx + nx * half_w, cy + ny * half_w))
        lower.append((cx - nx * half_w, cy - ny * half_w))

    return upper + list(reversed(lower))


def _arrow_head_poly_pts(
    x1: float, y1: float, x2: float, y2: float,
    width: float,
) -> list[tuple[float, float]]:
    """채워진 삼각 화살촉 폴리곤 [(x,y)...] in FITZ 좌표."""
    pts = _arrow_head_points(x1, y1, x2, y2, width)
    if pts is None:
        return []
    (ax1, ay1), (ax2, ay2) = pts
    return [(ax1, ay1), (x2, y2), (ax2, ay2)]


def _triangle_arrow_pts(
    x1: float, y1: float, x2: float, y2: float,
    width: float,
) -> list[tuple[float, float]]:
    """삼각형 화살표 폴리곤: 시작점(x1,y1)에서 넓고 끝점(x2,y2)이 꼭짓점."""
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    if L < 2.0:
        return []
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    half_w = max(width * 2.0, 6.0)
    return [
        (x1 + nx * half_w, y1 + ny * half_w),
        (x2, y2),
        (x1 - nx * half_w, y1 - ny * half_w),
    ]


def _block_arrow_pts(
    x1: float, y1: float, x2: float, y2: float,
    width: float,
    scale: float = 1.0,
) -> list[tuple[float, float]]:
    """몸통 + 화살촉으로 이루어진 블록 화살표 꼭짓점 목록을 만든다.

    scale: 좌표계 배율(씬 미리보기는 view.zoom()). 최소 굵기 같은 절대
    상수까지 함께 늘려야 미리보기와 적용 결과가 같은 크기가 된다.
    """
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 4.0:
        return []
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    shaft_half = scale * max(width * 0.42, 2.2)
    head_len = min(scale * max(width * 4.0, 16.0), max(10.0 * scale, length * 0.42))
    head_half = scale * max(width * 1.35, max(width * 0.42, 2.2) * 1.9, 7.0)
    base_x = x2 - ux * head_len
    base_y = y2 - uy * head_len
    return [
        (x1 + nx * shaft_half, y1 + ny * shaft_half),
        (base_x + nx * shaft_half, base_y + ny * shaft_half),
        (base_x + nx * head_half, base_y + ny * head_half),
        (x2, y2),
        (base_x - nx * head_half, base_y - ny * head_half),
        (base_x - nx * shaft_half, base_y - ny * shaft_half),
        (x1 - nx * shaft_half, y1 - ny * shaft_half),
    ]


def _block_double_arrow_pts(
    x1: float, y1: float, x2: float, y2: float,
    width: float,
    scale: float = 1.0,
) -> list[tuple[float, float]]:
    """양쪽 끝에 화살촉이 있는 블록 화살표 꼭짓점 목록을 만든다."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 8.0:
        return []
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    shaft_half = scale * max(width * 0.42, 2.2)
    head_len = min(scale * max(width * 3.6, 14.0), max(8.0 * scale, length * 0.28))
    head_half = scale * max(width * 1.35, max(width * 0.42, 2.2) * 1.9, 7.0)
    left_x = x1 + ux * head_len
    left_y = y1 + uy * head_len
    right_x = x2 - ux * head_len
    right_y = y2 - uy * head_len
    return [
        (x1, y1),
        (left_x + nx * head_half, left_y + ny * head_half),
        (left_x + nx * shaft_half, left_y + ny * shaft_half),
        (right_x + nx * shaft_half, right_y + ny * shaft_half),
        (right_x + nx * head_half, right_y + ny * head_half),
        (x2, y2),
        (right_x - nx * head_half, right_y - ny * head_half),
        (right_x - nx * shaft_half, right_y - ny * shaft_half),
        (left_x - nx * shaft_half, left_y - ny * shaft_half),
        (left_x - nx * head_half, left_y - ny * head_half),
    ]


def _wavy_arrow_strokes(x1: float, y1: float, x2: float, y2: float,
                        width: float,
                        head_mode: str) -> list[list[tuple[float, float]]]:
    shaft_end = _shaft_end_point(x1, y1, x2, y2, width)
    body = _wave_points(x1, y1, shaft_end[0], shaft_end[1], amplitude=max(2.0, width * 0.9))
    strokes = [body]
    points = _arrow_head_points(x1, y1, x2, y2, width)
    if points is None:
        return strokes
    (ax1, ay1), (ax2, ay2) = points
    tip = body[-1]
    if head_mode == 'open':
        strokes.append([(ax1, ay1), tip])
        strokes.append([tip, (ax2, ay2)])
    else:
        strokes.append([(ax1, ay1), tip, (ax2, ay2), (ax1, ay1)])
    return strokes


class LineTool(BaseTool):
    name = 'line'
    label = '직선'
    cursor = Qt.CursorShape.CrossCursor
    shortcut = 'L'

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
            pen = QPen(style.color, scene_width(style.width, view))
            item.setPen(pen)
        else:
            item = QGraphicsLineItem()
            w = style.width * 3.0 if style.is_emphasized() else style.width
            pen = QPen(style.color, scene_width(w, view))
            if style.dashes:
                pen.setDashPattern(scene_dashes(style.dashes, w))
            item.setPen(pen)
        item.setZValue(10)
        view.scene().addItem(item)
        self._preview = item

    def on_move(self, pos, event, view):
        if not self._start or not self._preview:
            return
        style = tool_style(self.name)
        if style.is_wavy():
            z = view.zoom()
            self._preview.setPath(_path_from_points(_wave_points(
                self._start.x(), self._start.y(), pos.x(), pos.y(),
                amplitude=max(2.0, style.width * 0.9) * z, wavelength=18.0 * z)))
        else:
            self._preview.setLine(self._start.x(), self._start.y(), pos.x(), pos.y())

    def on_release(self, pos, event, view):
        if not self._start:
            return
        preview = self._preview
        self._preview = None
        page_idx, p1 = resolve_page_and_fitz_pt(view, self._start)
        offset = view.page_offset(page_idx)
        p2 = scene_to_fitz_pt(pos, view.zoom(), offset)
        self._start = None
        if abs(p1.x - p2.x) < 2 and abs(p1.y - p2.y) < 2:
            if preview:
                view.scene().removeItem(preview)
            return
        style = tool_style(self.name)
        if style.is_wavy():
            pending = PendingAnnotation(
                uid=view.pending_layer().next_uid(),
                page_index=page_idx,
                tool_name=self.name,
                annot_type='ink',
                points=[_wave_points(p1.x, p1.y, p2.x, p2.y, amplitude=max(1.2, style.width * 0.6), wavelength=14.0)],
                stroke_color=style.fitz_color(),
                border_width=max(0.5, style.width),
                q_item=preview,
            )
            view.pending_layer().add(pending)
        else:
            w = style.width * 3.0 if style.is_emphasized() else style.width
            pending = PendingAnnotation(
                uid=view.pending_layer().next_uid(),
                page_index=page_idx,
                tool_name=self.name,
                annot_type='line',
                p1=p1,
                p2=p2,
                stroke_color=style.fitz_color(),
                border_width=max(0.5, w),
                dashes=style.dashes if style.dashes else None,
                line_end_start=0,
                line_end_end=0,
                q_item=preview,
            )
            view.pending_layer().add(pending)
        view.doc().mark_dirty()
        view.notify_pending_changed()


class ArrowTool(BaseTool):
    name = 'arrow'
    label = '화살표'
    cursor = Qt.CursorShape.CrossCursor
    shortcut = 'A'

    def __init__(self):
        self._start: QPointF | None = None
        self._preview: QGraphicsItemGroup | None = None

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def on_press(self, pos, event, view):
        self._start = pos
        item = QGraphicsItemGroup()
        item.setZValue(10)
        view.scene().addItem(item)
        self._preview = item

    def on_move(self, pos, event, view):
        if not self._start or not self._preview:
            return
        style = tool_style(self.name)
        _build_arrow_preview(self._preview, self._start.x(), self._start.y(), pos.x(), pos.y(), style, view.zoom())

    def on_release(self, pos, event, view):
        if not self._start:
            return
        preview = self._preview
        self._preview = None
        page_idx, p1 = resolve_page_and_fitz_pt(view, self._start)
        offset = view.page_offset(page_idx)
        p2 = scene_to_fitz_pt(pos, view.zoom(), offset)
        self._start = None
        if abs(p1.x - p2.x) < 2 and abs(p1.y - p2.y) < 2:
            if preview:
                view.scene().removeItem(preview)
            return
        style = tool_style(self.name)
        head_mode = getattr(style, 'arrow_head', 'closed')
        if style.is_emphasized():
            if preview:
                view.scene().removeItem(preview)
            tri = _block_arrow_pts(p1.x, p1.y, p2.x, p2.y, style.width)
            pending = PendingAnnotation(
                uid=view.pending_layer().next_uid(),
                page_index=page_idx,
                tool_name=self.name,
                annot_type='polygon',
                points=[tri] if tri else [],
                stroke_color=style.fitz_color(),
                fill_color=style.fitz_color(),
                border_width=max(0.5, style.width * 0.18),
            )
            view.pending_layer().add(pending)
            view.rebuild_pending_item(pending)
        else:
            # 몸통 + 화살촉을 한 항목으로 — 점선/물결/열린 화살촉 모두 같은 길로
            # 처리하고 화살촉 크기는 우리가 정한다 (/LE 폭주 방지).
            if preview:
                view.scene().removeItem(preview)
            closed = head_mode != 'open'
            strokes = _arrow_strokes(p1.x, p1.y, p2.x, p2.y, style.width,
                                     closed=closed, wavy=style.is_wavy())
            pending = PendingAnnotation(
                uid=view.pending_layer().next_uid(),
                page_index=page_idx,
                tool_name=self.name,
                annot_type='arrow',
                points=strokes,
                stroke_color=style.fitz_color(),
                fill_color=_arrow_fill_color(style) or style.fitz_color(),
                border_width=max(0.5, style.width),
                dashes=style.dashes if (style.dashes and not style.is_wavy()) else None,
                line_end_end=1 if closed else 0,
            )
            view.pending_layer().add(pending)
            view.rebuild_pending_item(pending)
        view.doc().mark_dirty()
        view.notify_pending_changed()


class DoubleArrowTool(BaseTool):
    name = 'double_arrow'
    label = '\u2194 \uc591\ubc29\ud5a5 \ud654\uc0b4\ud45c'
    cursor = Qt.CursorShape.CrossCursor
    shortcut = None

    def __init__(self):
        self._start: QPointF | None = None
        self._preview: QGraphicsItemGroup | None = None

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def on_press(self, pos, event, view):
        self._start = pos
        item = QGraphicsItemGroup()
        item.setZValue(10)
        view.scene().addItem(item)
        self._preview = item

    def on_move(self, pos, event, view):
        if not self._start or not self._preview:
            return
        style = tool_style(self.name)
        _build_double_arrow_preview(
            self._preview,
            self._start.x(), self._start.y(),
            pos.x(), pos.y(),
            style,
            view.zoom(),
        )

    def on_release(self, pos, event, view):
        if not self._start:
            return
        preview = self._preview
        self._preview = None
        page_idx, p1 = resolve_page_and_fitz_pt(view, self._start)
        offset = view.page_offset(page_idx)
        p2 = scene_to_fitz_pt(pos, view.zoom(), offset)
        self._start = None
        if abs(p1.x - p2.x) < 2 and abs(p1.y - p2.y) < 2:
            if preview:
                view.scene().removeItem(preview)
            return
        style = tool_style(self.name)
        head_mode = getattr(style, 'arrow_head', 'closed')
        if style.is_emphasized():
            if preview:
                view.scene().removeItem(preview)
            poly = _block_double_arrow_pts(p1.x, p1.y, p2.x, p2.y, style.width)
            pending = PendingAnnotation(
                uid=view.pending_layer().next_uid(),
                page_index=page_idx,
                tool_name=self.name,
                annot_type='polygon',
                points=[poly] if poly else [],
                stroke_color=style.fitz_color(),
                fill_color=style.fitz_color(),
                border_width=max(0.5, style.width * 0.18),
            )
            view.pending_layer().add(pending)
            view.rebuild_pending_item(pending)
        else:
            # 몸통 + 양쪽 화살촉을 한 항목으로 (화살촉 크기 제어)
            if preview:
                view.scene().removeItem(preview)
            closed = head_mode != 'open'
            strokes = _arrow_strokes(p1.x, p1.y, p2.x, p2.y, style.width,
                                     closed=closed, double=True,
                                     wavy=style.is_wavy())
            pending = PendingAnnotation(
                uid=view.pending_layer().next_uid(),
                page_index=page_idx,
                tool_name=self.name,
                annot_type='arrow',
                points=strokes,
                stroke_color=style.fitz_color(),
                fill_color=_arrow_fill_color(style) or style.fitz_color(),
                border_width=max(0.5, style.width),
                dashes=style.dashes if (style.dashes and not style.is_wavy()) else None,
                line_end_end=1 if closed else 0,
            )
            view.pending_layer().add(pending)
            view.rebuild_pending_item(pending)
        view.doc().mark_dirty()
        view.notify_pending_changed()
