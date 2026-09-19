from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import fitz
from utils.errlog import swallowed

logger = logging.getLogger('pdf_editor')


def _int_dashes(dashes, width: float = 1.0) -> list[int] | None:
    """대시 패턴(선 굵기의 배수) → PDF 대시 배열(정수 포인트).

    두 가지를 함께 처리한다.
    ① PyMuPDF 는 실수 대시값을 조용히 버리고 선을 실선으로 만든다
       ([6.0, 4.0] → style 'S'). 프리셋이 전부 실수라 점선·파선이 모두
       실선으로 저장되고 있었다.
    ② 대시 길이는 선 굵기에 비례해야 한다. 절대 포인트로 넣으면 굵은 선에서
       획 끝(둥근 캡)이 간격을 메워 실선처럼 보인다. Qt 의 QPen 대시 패턴과
       같은 의미(굵기의 배수)로 맞춰 미리보기와도 일치시킨다.
    """
    if not dashes:
        return None
    w = max(0.2, float(width))
    out = [max(1, int(round(float(v) * w))) for v in dashes]
    return out or None


@dataclass
class PendingAnnotation:
    uid: int
    page_index: int
    tool_name: str
    annot_type: str

    fitz_rect: fitz.Rect | None = None
    points: list | None = None
    p1: fitz.Point | None = None
    p2: fitz.Point | None = None

    stroke_color: tuple | None = (0.0, 0.0, 0.0)
    fill_color: tuple | None = None
    opacity: float = 1.0
    border_width: float = 1.5
    dashes: list | None = None

    text: str = ''
    fontsize: float = 11.0
    fontname: str = 'Helv'
    fontfile: str = ''
    text_color: tuple = (0.0, 0.0, 0.0)
    text_align: int = 0
    stamp_index: int = 0
    line_end_start: int = 0
    line_end_end: int = 0
    # 복합 화살표('arrow')용 — 커밋 시 만들어진 부속 어노테이션 xref (undo용)
    extra_xrefs: list = field(default_factory=list, repr=False)
    image_path: str = ''
    rotation_deg: float = 0.0   # 이미지 어노테이션 회전 각도

    q_item: Any = field(default=None, repr=False)
    committed_xref: int | None = field(default=None, repr=False)  # 커밋 후 xref (undo용)

    def bounding_fitz_rect(self) -> fitz.Rect | None:
        pad = max(4.0, float(self.border_width) * 2.0)
        if self.fitz_rect is not None:
            return fitz.Rect(
                self.fitz_rect.x0 - pad,
                self.fitz_rect.y0 - pad,
                self.fitz_rect.x1 + pad,
                self.fitz_rect.y1 + pad,
            )
        if self.p1 is not None and self.p2 is not None:
            extra = max(pad, float(self.border_width) * 5.0)
            return fitz.Rect(
                min(self.p1.x, self.p2.x) - extra,
                min(self.p1.y, self.p2.y) - extra,
                max(self.p1.x, self.p2.x) + extra,
                max(self.p1.y, self.p2.y) + extra,
            )
        if self.points:
            all_pts = [pt for stroke in self.points for pt in stroke]
            if all_pts:
                xs = [p[0] for p in all_pts]
                ys = [p[1] for p in all_pts]
                return fitz.Rect(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
        return None

    def move(self, dx: float, dy: float):
        if self.fitz_rect is not None:
            rect = self.fitz_rect
            self.fitz_rect = fitz.Rect(rect.x0 + dx, rect.y0 + dy, rect.x1 + dx, rect.y1 + dy)
        if self.p1 is not None:
            self.p1 = fitz.Point(self.p1.x + dx, self.p1.y + dy)
        if self.p2 is not None:
            self.p2 = fitz.Point(self.p2.x + dx, self.p2.y + dy)
        if self.points is not None:
            self.points = [[(x + dx, y + dy) for x, y in stroke] for stroke in self.points]

    def geometry_snapshot(self) -> dict:
        return {
            'fitz_rect':    fitz.Rect(self.fitz_rect) if self.fitz_rect is not None else None,
            'p1':           fitz.Point(self.p1.x, self.p1.y) if self.p1 is not None else None,
            'p2':           fitz.Point(self.p2.x, self.p2.y) if self.p2 is not None else None,
            'points':       [[(float(x), float(y)) for x, y in stroke] for stroke in self.points] if self.points is not None else None,
            'rotation_deg': self.rotation_deg,
        }

    def resize_from_snapshot(self, snapshot: dict, source_rect: fitz.Rect, target_rect: fitz.Rect):
        src_w = max(1e-6, float(source_rect.width))
        src_h = max(1e-6, float(source_rect.height))
        dst_w = max(1e-6, float(target_rect.width))
        dst_h = max(1e-6, float(target_rect.height))

        def map_xy(x: float, y: float) -> tuple[float, float]:
            rx = (x - source_rect.x0) / src_w
            ry = (y - source_rect.y0) / src_h
            return target_rect.x0 + rx * dst_w, target_rect.y0 + ry * dst_h

        snap_rect = snapshot.get('fitz_rect')
        if snap_rect is not None:
            self.fitz_rect = fitz.Rect(target_rect)
        else:
            self.fitz_rect = None

        snap_p1 = snapshot.get('p1')
        snap_p2 = snapshot.get('p2')
        if snap_p1 is not None:
            x, y = map_xy(snap_p1.x, snap_p1.y)
            self.p1 = fitz.Point(x, y)
        else:
            self.p1 = None
        if snap_p2 is not None:
            x, y = map_xy(snap_p2.x, snap_p2.y)
            self.p2 = fitz.Point(x, y)
        else:
            self.p2 = None

        snap_points = snapshot.get('points')
        if snap_points is not None:
            self.points = [
                [map_xy(float(x), float(y)) for x, y in stroke]
                for stroke in snap_points
            ]
        else:
            self.points = None

    def rotate_from_snapshot(self, snapshot: dict, cx: float, cy: float, angle_rad: float):
        """snapshot 기준으로 (cx,cy) 중심 angle_rad 만큼 회전 적용."""
        import math
        cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)

        def rot(x: float, y: float) -> tuple[float, float]:
            dx, dy = x - cx, y - cy
            return cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a

        snap_p1 = snapshot.get('p1')
        snap_p2 = snapshot.get('p2')
        snap_rect = snapshot.get('fitz_rect')
        snap_pts = snapshot.get('points')

        if snap_p1 is not None:
            self.p1 = fitz.Point(*rot(snap_p1.x, snap_p1.y))
        if snap_p2 is not None:
            self.p2 = fitz.Point(*rot(snap_p2.x, snap_p2.y))

        if snap_pts is not None:
            self.points = [[rot(x, y) for x, y in stroke] for stroke in snap_pts]
        elif snap_rect is not None:
            if self.annot_type in ('image', 'freetext', 'text', 'direct_text'):
                # 회전 각도를 누적 저장하고 중심점만 이동 (polygon 변환 없음)
                prev_deg = snapshot.get('rotation_deg', 0.0)
                self.rotation_deg = prev_deg + math.degrees(angle_rad)
                orig_cx = (snap_rect.x0 + snap_rect.x1) / 2
                orig_cy = (snap_rect.y0 + snap_rect.y1) / 2
                new_cx, new_cy = rot(orig_cx, orig_cy)
                hw = snap_rect.width  / 2
                hh = snap_rect.height / 2
                self.fitz_rect = fitz.Rect(new_cx - hw, new_cy - hh,
                                           new_cx + hw, new_cy + hh)
            else:
                # 일반 rect → 4개 꼭짓점 회전 → polygon으로 변환
                x0, y0, x1, y1 = snap_rect.x0, snap_rect.y0, snap_rect.x1, snap_rect.y1
                corners = [rot(x0, y0), rot(x1, y0), rot(x1, y1), rot(x0, y1)]
                self.points = [corners]
                self.fitz_rect = None
                self.annot_type = 'polygon'

    def remove_from_scene(self):
        if self.q_item is not None:
            try:
                scene = self.q_item.scene()
                if scene is not None:
                    scene.removeItem(self.q_item)
            except RuntimeError:
                swallowed()
            self.q_item = None

    def commit(self, page: fitz.Page) -> 'fitz.Annot | None':
        """페이지에 어노테이션을 기록한다.

        어노테이션 객체를 생성하는 타입은 그 객체를 반환하고,
        페이지 콘텐츠에 직접 굽는 타입(direct_text/image 등)은 None을 반환.
        """
        annot = None
        if self.annot_type == 'rect':
            annot = page.add_rect_annot(self.fitz_rect)
            annot.set_colors(stroke=self.stroke_color, fill=self.fill_color)
            annot.set_opacity(self.opacity)
            kwargs = {'width': max(0.1, self.border_width)}
            _d = _int_dashes(self.dashes, self.border_width)
            if _d:
                kwargs['dashes'] = _d
            annot.set_border(**kwargs)
        elif self.annot_type == 'ink':
            annot = page.add_ink_annot(self.points)
            annot.set_colors(stroke=self.stroke_color)
            kwargs = {'width': max(0.5, self.border_width)}
            _d = _int_dashes(self.dashes, self.border_width)
            if _d:
                kwargs['dashes'] = _d
            annot.set_border(**kwargs)
        elif self.annot_type == 'circle':
            annot = page.add_circle_annot(self.fitz_rect)
            annot.set_colors(stroke=self.stroke_color, fill=self.fill_color)
            kwargs = {'width': max(0.5, self.border_width)}
            _d = _int_dashes(self.dashes, self.border_width)
            if _d:
                kwargs['dashes'] = _d
            annot.set_border(**kwargs)
        elif self.annot_type == 'line':
            annot = page.add_line_annot(self.p1, self.p2)
            annot.set_colors(stroke=self.stroke_color, fill=self.fill_color)
            kwargs = {'width': max(0.5, self.border_width)}
            _d = _int_dashes(self.dashes, self.border_width)
            if _d:
                kwargs['dashes'] = _d
            annot.set_border(**kwargs)
            if self.line_end_start or self.line_end_end:
                annot.set_line_ends(self.line_end_start, self.line_end_end)
        elif self.annot_type == 'arrow':
            # 몸통 + 화살촉을 우리가 정한 크기로 그린다.
            # PDF 의 /LE 화살촉은 크기를 지정할 수 없고 뷰어가 선 굵기에
            # 비례해(MuPDF 는 10.25배) 그려서 굵은 선일수록 머리가 폭주한다.
            # 몸통은 ink 로 그려 점선·굵기를 그대로 살린다.
            strokes = list(self.points or [])
            if not strokes:
                return None
            self.extra_xrefs = []
            shaft = page.add_ink_annot([strokes[0]])
            shaft.set_colors(stroke=self.stroke_color)
            kwargs = {'width': max(0.5, self.border_width)}
            _d = _int_dashes(self.dashes, self.border_width)
            if _d:
                kwargs['dashes'] = _d
            shaft.set_border(**kwargs)
            shaft.set_opacity(self.opacity)
            shaft.update()
            closed = bool(self.line_end_end)
            for head in strokes[1:]:
                if len(head) < 2:
                    continue
                if closed:
                    head_annot = page.add_polygon_annot(head)
                    head_annot.set_colors(stroke=self.stroke_color,
                                          fill=self.fill_color or self.stroke_color)
                    head_annot.set_border(width=max(0.3, self.border_width * 0.12))
                else:
                    # 열린 화살촉(∧) — 채우지 않고 선으로만
                    head_annot = page.add_ink_annot([head])
                    head_annot.set_colors(stroke=self.stroke_color)
                    head_annot.set_border(width=max(0.5, self.border_width))
                head_annot.set_opacity(self.opacity)
                head_annot.update()
                xref = getattr(head_annot, 'xref', None)
                if xref:
                    self.extra_xrefs.append(xref)
            return shaft
        elif self.annot_type == 'polygon':
            annot = page.add_polygon_annot(self.points[0] if self.points else [])
            annot.set_colors(stroke=self.stroke_color, fill=self.fill_color)
            annot.set_opacity(self.opacity)
            kwargs = {'width': max(0.5, self.border_width)}
            _d = _int_dashes(self.dashes, self.border_width)
            if _d:
                kwargs['dashes'] = _d
            annot.set_border(**kwargs)
        elif self.annot_type == 'freetext':
            annot = page.add_freetext_annot(
                self.fitz_rect,
                self.text,
                fontsize=self.fontsize,
                fontname=self.fontname,
                align=self.text_align,
                text_color=list(self.text_color),
                fill_color=None,
                border_color=None,
            )
            rot_deg = getattr(self, 'rotation_deg', 0.0)
            if rot_deg != 0.0:
                try:
                    annot.set_rotation(int(rot_deg) % 360)
                except Exception:
                    swallowed()
        elif self.annot_type == 'text':
            annot = page.add_text_annot(fitz.Point(self.fitz_rect.x0, self.fitz_rect.y0), self.text, icon='Note')
            fill = self.fill_color or (1.0, 0.9, 0.0)
            annot.set_colors(stroke=[1.0, 0.8, 0.0], fill=list(fill))
            if self.opacity is not None and self.opacity < 0.99:
                annot.set_opacity(max(0.1, float(self.opacity)))
        elif self.annot_type == 'index_tab':
            # 색 탭 + 라벨을 페이지에 굽는다 (저장 후에도 보이는 인덱스 포스트잇)
            rect = self.fitz_rect
            fill = self.fill_color or (0.36, 0.68, 0.94)
            fop = max(0.1, float(self.opacity)) if (self.opacity is not None and self.opacity < 0.99) else 1.0
            try:
                shape = page.new_shape()
                try:
                    shape.draw_rect(rect, radius=0.25)   # 신버전: 둥근 모서리
                except TypeError:
                    shape.draw_rect(rect)                 # 구버전 폴백
                shape.finish(color=None, fill=list(fill), fill_opacity=fop)
                shape.commit()
            except Exception:
                logger.exception('[PendingAnnotation] index_tab rect error')
                raise
            if self.text:
                lum = 0.299*fill[0] + 0.587*fill[1] + 0.114*fill[2]
                tcolor = [0.08, 0.08, 0.08] if lum > 0.6 else [1.0, 1.0, 1.0]
                # 세로쓰기(text_align==99)는 글자를 한 줄에 하나씩 쌓아 표현
                # (insert_textbox 는 회전을 지원하지 않음)
                label = '\n'.join(list(self.text)) if self.text_align == 99 else self.text
                _ko = any(0xAC00 <= ord(c) <= 0xD7A3 for c in self.text)
                pad = 0.6
                inner = fitz.Rect(rect.x0 + pad, rect.y0 + pad,
                                  rect.x1 - pad, rect.y1 - pad)
                fkwargs = {'align': fitz.TEXT_ALIGN_CENTER, 'color': tcolor}
                if _ko:
                    fkwargs['fontname'] = 'korea'
                elif self.fontfile and __import__('os').path.exists(self.fontfile):
                    fkwargs['fontfile'] = self.fontfile
                    fkwargs['fontname'] = self.fontname or 'F0'
                else:
                    fkwargs['fontname'] = self.fontname or 'helv'
                # 작은 탭에 글자가 안 들어가면 들어갈 때까지 크기를 줄인다
                fs = float(self.fontsize)
                inserted = False
                for _ in range(8):
                    try:
                        rc = page.insert_textbox(inner, label, fontsize=fs, **fkwargs)
                        if rc >= 0:
                            inserted = True
                            break
                    except Exception:
                        logger.exception('[PendingAnnotation] index_tab text error')
                        break
                    fs *= 0.85
                    if fs < 4:
                        break
                if not inserted:
                    logger.warning('[PendingAnnotation] index_tab 라벨이 탭에 안 들어감: %r', self.text)
            return
        elif self.annot_type == 'stamp':
            from tools.stamp_tool import STAMP_NAMES, _stamp_idx
            stamp_name = STAMP_NAMES[self.stamp_index] if self.stamp_index < len(STAMP_NAMES) else 'Draft'
            annot = page.add_stamp_annot(self.fitz_rect, stamp=_stamp_idx(stamp_name))
        elif self.annot_type == 'direct_text':
            import os as _os
            font_path = self.fontfile or ''
            font_name = self.fontname or 'KPBT'
            try:
                if font_path and _os.path.exists(font_path):
                    page.insert_textbox(
                        self.fitz_rect,
                        self.text,
                        fontfile=font_path,
                        fontname=font_name,
                        fontsize=self.fontsize,
                        color=list(self.text_color),
                        align=self.text_align,
                    )
                else:
                    page.insert_textbox(
                        self.fitz_rect,
                        self.text,
                        fontname=self.fontname or 'helv',
                        fontsize=self.fontsize,
                        color=list(self.text_color),
                        align=self.text_align,
                    )
            except Exception:
                logger.exception('[PendingAnnotation] direct_text error')
                raise
            return
        elif self.annot_type == 'image':
            try:
                img_path = self.image_path
                needs_pil = self.rotation_deg != 0.0 or self.opacity < 0.99
                if needs_pil:
                    from PIL import Image as _PILImage
                    import tempfile, os as _os
                    pil_img = _PILImage.open(img_path).convert('RGBA')
                    if self.rotation_deg != 0.0:
                        pil_img = pil_img.rotate(-self.rotation_deg, expand=True,
                                                 resample=_PILImage.BICUBIC)
                    if self.opacity < 0.99:
                        r, g, b, a = pil_img.split()
                        a = a.point(lambda x: int(x * self.opacity))
                        pil_img = _PILImage.merge('RGBA', (r, g, b, a))
                    tmp = tempfile.NamedTemporaryFile(
                        suffix='.png', delete=False,
                        dir=_os.path.dirname(img_path))
                    pil_img.save(tmp.name)
                    tmp.close()
                    img_path = tmp.name
                page.insert_image(self.fitz_rect, filename=img_path)
            except Exception:
                logger.exception('[PendingAnnotation] image commit error')
                raise
            return
        elif self.annot_type == 'image_bytes':
            try:
                image_bytes = getattr(self, '_image_bytes', None)
                if image_bytes:
                    page.insert_image(self.fitz_rect, stream=image_bytes)
                else:
                    logger.warning('[PendingAnnotation] image_bytes commit: _image_bytes \ub370\uc774\ud130 \uc5c6\uc74c')
            except Exception:
                logger.exception('[PendingAnnotation] image_bytes commit error')
                raise
            return
        elif self.annot_type == 'ink_outlined':
            # 유선형 폴리곤: 각 polygon을 채워진 polygon 어노테이션으로 커밋
            for poly_pts in (self.points or []):
                if not poly_pts or len(poly_pts) < 3:
                    continue
                annot = page.add_polygon_annot(poly_pts)
                annot.set_colors(stroke=self.stroke_color, fill=self.stroke_color)
                annot.set_border(width=0.3)
                annot.update()
            return

        if annot is not None:
            annot.update()
        return annot


class PendingLayer:
    """Manage unsaved annotations per page."""

    def __init__(self):
        self._annots: list[PendingAnnotation] = []
        self._uid_counter = 0

    def next_uid(self) -> int:
        self._uid_counter += 1
        return self._uid_counter

    def add(self, pa: PendingAnnotation):
        self._annots.append(pa)

    def remove_uid(self, uid: int) -> PendingAnnotation | None:
        for index, annot in enumerate(self._annots):
            if annot.uid == uid:
                return self._annots.pop(index)
        return None

    def for_page(self, page_index: int) -> list[PendingAnnotation]:
        return [annot for annot in self._annots if annot.page_index == page_index]

    def all(self) -> list[PendingAnnotation]:
        return list(self._annots)

    def count(self) -> int:
        return len(self._annots)

    def clear_q_items(self):
        for annot in self._annots:
            annot.q_item = None

    def remove_all_from_scene_and_clear(self):
        for annot in self._annots:
            annot.remove_from_scene()
        self._annots.clear()

    def commit_all(self, fitz_doc: fitz.Document):
        committed: list[PendingAnnotation] = []
        failed: list[PendingAnnotation] = []
        remaining: list[PendingAnnotation] = []
        for annot in self._annots:
            try:
                page = fitz_doc.load_page(annot.page_index)
                created = annot.commit(page)
                annot.committed_xref = getattr(created, 'xref', None)
                annot.remove_from_scene()
                committed.append(annot)
            except Exception:
                logger.exception('[PendingLayer] commit error uid=%d', annot.uid)
                failed.append(annot)
                remaining.append(annot)
        self._annots = remaining
        return committed, failed
