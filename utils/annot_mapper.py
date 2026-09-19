# utils/annot_mapper.py — fitz 좌표 ↔ Qt Scene 좌표 변환
from __future__ import annotations
import fitz
from PySide6.QtCore import QPointF, QRectF


def scene_to_fitz_pt(scene_pt: QPointF, zoom: float,
                     offset: QPointF | None = None) -> fitz.Point:
    """Qt Scene 픽셀 좌표 → fitz 포인트 좌표 (72dpi 기준).
    offset: 해당 페이지의 씬 내 좌상단 오프셋 (양면 모드에서 오른쪽 페이지 보정용).
    """
    ox = offset.x() if offset is not None else 0.0
    oy = offset.y() if offset is not None else 0.0
    return fitz.Point((scene_pt.x() - ox) / zoom, (scene_pt.y() - oy) / zoom)


def scene_to_fitz_rect(scene_rect: QRectF, zoom: float,
                       offset: QPointF | None = None) -> fitz.Rect:
    tl = scene_to_fitz_pt(scene_rect.topLeft(),    zoom, offset)
    br = scene_to_fitz_pt(scene_rect.bottomRight(), zoom, offset)
    return fitz.Rect(tl, br)


def fitz_to_scene_pt(pt: fitz.Point, zoom: float) -> QPointF:
    return QPointF(pt.x * zoom, pt.y * zoom)


def fitz_to_scene_rect(rect: fitz.Rect, zoom: float) -> QRectF:
    return QRectF(
        rect.x0 * zoom, rect.y0 * zoom,
        rect.width * zoom, rect.height * zoom,
    )


# ── view 기반 헬퍼 (양면 모드 오프셋 자동 보정) ──────────────────────────

def resolve_page_and_fitz_pt(view, scene_pos: QPointF) -> tuple[int, fitz.Point]:
    """씬 좌표 → (페이지 인덱스, fitz 좌표). 양면 모드 오프셋 자동 보정."""
    page_idx = view.page_at_scene(scene_pos)
    offset   = view.page_offset(page_idx)
    pt = fitz.Point(
        (scene_pos.x() - offset.x()) / view.zoom(),
        (scene_pos.y() - offset.y()) / view.zoom(),
    )
    return page_idx, pt


def resolve_page_and_fitz_rect(view, scene_rect: QRectF) -> tuple[int, fitz.Rect]:
    """씬 Rect → (페이지 인덱스, fitz Rect). 양면 모드 오프셋 자동 보정."""
    page_idx = view.page_at_scene(scene_rect.center())
    offset   = view.page_offset(page_idx)
    r = fitz.Rect(
        (scene_rect.x()      - offset.x()) / view.zoom(),
        (scene_rect.y()      - offset.y()) / view.zoom(),
        (scene_rect.right()  - offset.x()) / view.zoom(),
        (scene_rect.bottom() - offset.y()) / view.zoom(),
    )
    return page_idx, r
