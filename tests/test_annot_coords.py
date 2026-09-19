# tests/test_annot_coords.py — 주석 좌표 회귀 테스트
"""주석이 엉뚱한 자리에 찍히면 앱을 못 쓴다.

화면(Qt Scene) 좌표와 문서(fitz) 좌표를 오가는 변환은 확대율·양면 모드
오프셋이 얽혀 있어 조용히 틀리기 쉽다. 왕복 변환이 제자리로 돌아오는지를
확인한다 — 틀리면 주석이 확대할 때마다 밀린다.
"""
from __future__ import annotations

import fitz
import pytest
from PySide6.QtCore import QPointF, QRectF

from utils.annot_mapper import (
    scene_to_fitz_pt, scene_to_fitz_rect, fitz_to_scene_pt, fitz_to_scene_rect,
)
from tests.conftest import make_pdf


ZOOMS = [0.5, 1.0, 1.25, 2.0, 3.7]


@pytest.mark.parametrize('zoom', ZOOMS)
def test_point_roundtrip(zoom):
    """씬 → fitz → 씬 왕복이 제자리로 돌아와야 한다."""
    src = QPointF(321.5, 128.25)
    back = fitz_to_scene_pt(scene_to_fitz_pt(src, zoom), zoom)
    assert back.x() == pytest.approx(src.x(), abs=1e-6)
    assert back.y() == pytest.approx(src.y(), abs=1e-6)


@pytest.mark.parametrize('zoom', ZOOMS)
def test_rect_roundtrip(zoom):
    src = QRectF(40.0, 60.0, 220.5, 90.25)
    back = fitz_to_scene_rect(scene_to_fitz_rect(src, zoom), zoom)
    assert back.left() == pytest.approx(src.left(), abs=1e-6)
    assert back.top() == pytest.approx(src.top(), abs=1e-6)
    assert back.width() == pytest.approx(src.width(), abs=1e-6)
    assert back.height() == pytest.approx(src.height(), abs=1e-6)


@pytest.mark.parametrize('zoom', ZOOMS)
def test_offset_is_subtracted(zoom):
    """양면 모드에서 오른쪽 페이지 오프셋만큼 빼야 한다.

    (오프셋을 안 빼면 오른쪽 페이지 주석이 페이지 너비만큼 밀린다)
    """
    offset = QPointF(600.0 * zoom, 0.0)
    scene = QPointF(600.0 * zoom + 100.0 * zoom, 50.0 * zoom)
    pt = scene_to_fitz_pt(scene, zoom, offset)
    assert pt.x == pytest.approx(100.0, abs=1e-6)
    assert pt.y == pytest.approx(50.0, abs=1e-6)


def test_zoom_does_not_change_document_coords():
    """확대율을 바꿔도 같은 문서 위치를 가리켜야 한다.

    화면에서 같은 지점을 찍었다면(확대율에 비례한 씬 좌표), 문서 좌표는
    확대율과 무관하게 같아야 한다.
    """
    doc_pt = (150.0, 275.0)
    results = []
    for zoom in ZOOMS:
        scene = QPointF(doc_pt[0] * zoom, doc_pt[1] * zoom)
        p = scene_to_fitz_pt(scene, zoom)
        results.append((p.x, p.y))
    for x, y in results:
        assert x == pytest.approx(doc_pt[0], abs=1e-6)
        assert y == pytest.approx(doc_pt[1], abs=1e-6)


def test_highlight_annot_survives_save(doc, tmp_path):
    """주석을 넣고 저장했다가 다시 열면 같은 자리에 있어야 한다."""
    page = doc.fitz_page(0)
    rect = fitz.Rect(72, 200, 300, 300)
    page.add_highlight_annot(rect)
    out = tmp_path / 'annot.pdf'
    doc.save_copy(str(out))

    d = fitz.open(str(out))
    try:
        # 주의: list(d[0].annots()) 로 쓰면 임시 Page 가 먼저 수거되면서
        # 나중에 annot.rect 를 읽을 때 네이티브 크래시가 난다(잡히지도 않는다).
        # 반드시 페이지를 변수로 붙잡아 둘 것.
        page = d[0]
        annots = list(page.annots())
        assert len(annots) == 1, f'주석이 1개여야 하는데 {len(annots)}개'
        # rect 가 아니라 quadpoints 로 본다 — PyMuPDF 는 하이라이트의 rect 를
        # 실제 덮는 영역보다 바깥으로 부풀려 돌려준다(테두리 여유분).
        # 우리가 지켜야 할 값은 '어디를 덮었는가' = quadpoints 다.
        quads = annots[0].vertices
        xs = [x for x, _ in quads]
        ys = [y for _, y in quads]
        assert min(xs) == pytest.approx(rect.x0, abs=0.5)
        assert max(xs) == pytest.approx(rect.x1, abs=0.5)
        assert min(ys) == pytest.approx(rect.y0, abs=0.5)
        assert max(ys) == pytest.approx(rect.y1, abs=0.5)
    finally:
        d.close()


def test_annot_on_rotated_page_keeps_position(doc, tmp_path):
    """페이지를 회전해도 주석이 본문을 따라가야 한다.

    회전 후 주석 좌표가 페이지 밖으로 나가면 안 된다.
    """
    page = doc.fitz_page(0)
    page.add_highlight_annot(fitz.Rect(72, 200, 300, 300))
    doc.rotate_page(0, 90)
    out = tmp_path / 'rot_annot.pdf'
    doc.save_copy(str(out))

    d = fitz.open(str(out))
    try:
        page = d[0]                       # 위 주석 참고 — 페이지를 붙잡아야 한다
        annots = list(page.annots())
        assert len(annots) == 1
        r = annots[0].rect
        bounds = page.rect
        assert r.x0 >= bounds.x0 - 1 and r.x1 <= bounds.x1 + 1, \
            f'주석이 페이지 밖으로 나갔다: {r} vs {bounds}'
        assert r.y0 >= bounds.y0 - 1 and r.y1 <= bounds.y1 + 1, \
            f'주석이 페이지 밖으로 나갔다: {r} vs {bounds}'
    finally:
        d.close()
