# tools/stamp_tool.py — 스탬프
from __future__ import annotations
import os
import sys

def _stamp1_path(fn: str) -> str:
    """개발 환경과 PyInstaller exe 환경 모두에서 stamp1 이미지 경로 반환."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, 'stamp1', fn)
import hashlib
import tempfile
try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None
from datetime import datetime
import fitz
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPen, QBrush, QColor, QFont
from PySide6.QtWidgets import QInputDialog, QGraphicsEllipseItem, QGraphicsSimpleTextItem
from tools.base_tool import BaseTool
from utils.annot_mapper import resolve_page_and_fitz_pt, scene_to_fitz_pt
from utils.pending_layer import PendingAnnotation
from ui.dialogs.stamp_manager_dialog import load_custom_stamps

STAMP_NAMES = [
    'Approved', 'AsIs', 'Confidential', 'Departmental',
    'Draft', 'Experimental', 'Expired', 'Final',
    'ForComment', 'ForPublicRelease', 'NotApproved',
    'NotForPublicRelease', 'Sold', 'TopSecret',
]

def format_stamp_label(name: str) -> str:
    import re
    if not name:
        return ''
    spaced = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
    return spaced.strip()

def _stamp_idx(name: str) -> int:
    """스탬프 이름 → fitz add_stamp_annot() 인덱스.
    fitz.STAMP_<Name> 상수를 우선 사용하고, 없으면 런타임 확인값으로 폴백."""
    v = getattr(fitz, f'STAMP_{name}', None)
    if v is not None:
        return v
    _FALLBACK = {
        'Approved': 0, 'AsIs': 1, 'Confidential': 2, 'Departmental': 3,
        'Experimental': 4, 'Expired': 5, 'Final': 6, 'ForComment': 7,
        'ForPublicRelease': 8, 'NotApproved': 9, 'NotForPublicRelease': 10,
        'Sold': 11, 'TopSecret': 12, 'Draft': 13,
    }
    return _FALLBACK.get(name, 0)

STAMP_KR = {
    '승인':       'Approved',
    '기밀':       'Confidential',
    '초안':       'Draft',
    '최종':       'Final',
    '검토요청':   'ForComment',
    '미승인':     'NotApproved',
    '극비':       'TopSecret',
    '만료':       'Expired',
    '실험':       'Experimental',
    '완료':       'Final',
}

DATE_STAMP_NAME = '__date_today__'
DATE_STAMP_LABEL = '오늘 날짜 (YYYY-MM-DD)'

SYMBOL_STAMPS = [
    {'id': '__sym_star__', 'label': '별모양', 'text': '★'},
    {'id': '__sym_circle__', 'label': '동그라미', 'text': '○'},
    {'id': '__sym_important__', 'label': '중요표시※', 'text': '※'},
    {'id': '__sym_check__', 'label': '체크', 'text': '✓'},
    {'id': '__sym_omicron_upper__', 'label': 'Ο', 'text': 'Ο'},
    {'id': '__sym_x__', 'label': '✕', 'text': '✕'},
    {'id': '__sym_arrow__', 'label': '>', 'text': '>'},
    {'id': '__sym_exclam__', 'label': '!', 'text': '!'},
    {'id': '__sym_question__', 'label': '?', 'text': '?'},
    {'id': '__sym_asterism__', 'label': '⁕', 'text': '⁕'},
    {'id': '__sym_omega_upper__', 'label': 'Ω', 'text': 'Ω'},
    {'id': '__sym_sigma_upper__', 'label': 'Σ', 'text': 'Σ'},
    {'id': '__sym_phi_upper__', 'label': 'Φ', 'text': 'Φ'},
    {'id': '__sym_omega_lower__', 'label': 'ω', 'text': 'ω'},
    {'id': '__sym_bullet__', 'label': '•', 'text': '•'},
    {'id': '__sym_degree__', 'label': '°', 'text': '°'},
]
SYMBOL_STAMP_MAP = {item['id']: item for item in SYMBOL_STAMPS}

# 도장 모양 정의 (id, 표시이름, 아이콘)
SEAL_SHAPES = [
    ('rect',          '직사각형',   '▭'),
    ('square',        '정사각형',   '□'),
    ('double_square', '이중 사각',  '⊡'),
    ('circle',        '원형',       '○'),
    ('double_circle', '이중 원형',  '◎'),
    ('oval',          '타원형',     '⬭'),
    ('hexagon',       '육각형',     '⬡'),
    ('diamond',       '마름모',     '◇'),
    ('postage',       '우표형',     '⊠'),
    ('star_circle',   '별장식 원형', '✦'),
    ('badge',         '배지형',     '⬒'),
]

CHARACTER_STAMPS = [
    # 아이들 캐릭터
    {'id': '__char_png_01__', 'image_path': _stamp1_path('1.png'),  'label': '잘했어요 (검정)'},
    {'id': '__char_png_02__', 'image_path': _stamp1_path('2.png'),  'label': '잘했어요 (파랑)'},
    {'id': '__char_png_03__', 'image_path': _stamp1_path('3.png'),  'label': '잘했어요 (보라)'},
    {'id': '__char_png_04__', 'image_path': _stamp1_path('4.png'),  'label': '잘했어요 (갈색)'},
    # 햄스터 캐릭터
    {'id': '__char_png_05__', 'image_path': _stamp1_path('5.png'),  'label': '훌륭해! (햄스터)'},
    {'id': '__char_png_06__', 'image_path': _stamp1_path('6.png'),  'label': '대단해! (햄스터)'},
    {'id': '__char_png_07__', 'image_path': _stamp1_path('7.png'),  'label': '놀라워! (햄스터)'},
    {'id': '__char_png_08__', 'image_path': _stamp1_path('8.png'),  'label': '최고야! (햄스터)'},
    # 토끼 캐릭터
    {'id': '__char_png_09__', 'image_path': _stamp1_path('9.png'),  'label': '칭찬해요! (토끼)'},
    {'id': '__char_png_10__', 'image_path': _stamp1_path('10.png'), 'label': '참잘했어요 (토끼)'},
    {'id': '__char_png_11__', 'image_path': _stamp1_path('11.png'), 'label': '완전 멋져! (토끼)'},
    {'id': '__char_png_12__', 'image_path': _stamp1_path('12.png'), 'label': '굉장해! (토끼)'},
    # 기타 스탬프
    {'id': '__char_png_13__', 'image_path': _stamp1_path('13.png'), 'label': 'FITNESS (파랑)'},
    {'id': '__char_png_14__', 'image_path': _stamp1_path('14.png'), 'label': 'FITNESS (빨강)'},
    {'id': '__char_png_15__', 'image_path': _stamp1_path('15.png'), 'label': 'FITNESS APPROVED'},
    {'id': '__char_png_16__', 'image_path': _stamp1_path('16.png'), 'label': 'FITNESS (검정)'},
    {'id': '__char_png_17__', 'image_path': _stamp1_path('17.png'), 'label': 'POST BOX'},
    {'id': '__char_png_18__', 'image_path': _stamp1_path('18.png'), 'label': '元旦 (한자)'},
    {'id': '__char_png_19__', 'image_path': _stamp1_path('19.png'), 'label': 'PERFECT'},
]
CHARACTER_STAMP_MAP = {s['id']: s for s in CHARACTER_STAMPS}

_CIRCLE_CHOICE = '① 원번호 (순차)'

_STAMP_CACHE_DIR = os.path.join(tempfile.gettempdir(), 'pdf_editor_stamp_cache')



def _prepare_transparent_stamp_png(image_path: str) -> str:
    if not image_path or not os.path.exists(image_path):
        return image_path
    try:
        stat = os.stat(image_path)
        key = hashlib.sha1(f'trans_v1|{image_path}|{stat.st_mtime_ns}|{stat.st_size}'.encode('utf-8')).hexdigest()[:16]
        out_path = os.path.join(_STAMP_CACHE_DIR, f'trans_{key}.png')
        if os.path.exists(out_path):
            return out_path
        from PIL import Image
        os.makedirs(_STAMP_CACHE_DIR, exist_ok=True)
        img = Image.open(image_path).convert('RGBA')
        px = list(img.getdata())
        new_px = []
        for r, g, b, a in px:
            if a == 0:
                new_px.append((r, g, b, a))
                continue
            if r >= 245 and g >= 245 and b >= 245:
                new_px.append((255, 255, 255, 0))
                continue
            if r >= 225 and g >= 225 and b >= 225:
                strength = max(0.0, min(1.0, (255 - min(r, g, b)) / 30.0))
                new_a = int(a * strength)
                new_px.append((r, g, b, new_a))
                continue
            new_px.append((r, g, b, a))
        img.putdata(new_px)
        img.save(out_path)
        return out_path
    except Exception:
        return image_path


def _resolve_windows_font_path(family: str) -> str | None:
    if not family or winreg is None:
        return None
    wanted = family.lower().replace(' ', '')
    font_dir = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts')
    key_paths = [
        r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts',
        r'SOFTWARE\Microsoft\Windows\CurrentVersion\Fonts',
    ]
    for hive in (getattr(winreg, 'HKEY_CURRENT_USER', None), getattr(winreg, 'HKEY_LOCAL_MACHINE', None)):
        if hive is None:
            continue
        for key_path in key_paths:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    count = winreg.QueryInfoKey(key)[1]
                    for idx in range(count):
                        try:
                            name, value, _ = winreg.EnumValue(key, idx)
                        except OSError:
                            continue
                        normalized = name.lower().replace(' ', '')
                        if wanted not in normalized:
                            continue
                        file_name = str(value)
                        full_path = file_name if os.path.isabs(file_name) else os.path.join(font_dir, file_name)
                        if os.path.exists(full_path):
                            return full_path
            except OSError:
                continue
    return None


def _stamp_style(name: str) -> tuple[str, str]:
    upper = (name or '').upper()
    if upper in {'APPROVED', 'FINAL'}:
        return '#1f8f5a', '#d9d9d9'
    if upper in {'NOT APPROVED', 'EXPIRED'}:
        return '#b71c1c', '#d9d9d9'
    if upper in {'CONFIDENTIAL', 'TOP SECRET'}:
        return '#f4511e', '#d9d9d9'
    return '#f4511e', '#d9d9d9'


def _color_hex_to_rgba(hex_str: str) -> tuple:
    """'#rrggbb' → (r, g, b, 255)"""
    h = (hex_str or '#cc0000').lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def _draw_seal_frame(draw, w: int, h: int, outer_color: str, shape: str) -> tuple:
    """도장 프레임을 그리고 텍스트 영역 (tx0, ty0, tx1, ty1)을 반환."""
    c = _color_hex_to_rgba(outer_color)
    s = min(w, h)
    out_w = max(7, int(s * 0.086))
    gap   = max(10, int(s * 0.115))
    in_w  = max(2,  int(s * 0.026))

    if shape == 'rect':
        outer_r = max(14, int(h * 0.22))
        inner_r = max(4, outer_r - gap)
        so = max(3, int(s * 0.03))
        draw.rounded_rectangle([so, so, w - so, h - so], radius=outer_r,
                                outline=(0, 0, 0, 50), width=max(3, out_w // 2))
        draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=outer_r,
                                outline=c, width=out_w)
        x0, y0, x1, y1 = gap, gap, w - gap - 1, h - gap - 1
        draw.rounded_rectangle([x0, y0, x1, y1], radius=inner_r,
                                fill=None, outline=c, width=in_w)
        pad = in_w + 5
        return x0 + pad, y0 + pad, x1 - pad, y1 - pad

    elif shape in ('square', 'double_square'):
        out_w = max(9, int(s * 0.092))
        gap   = max(10, int(s * 0.112))
        in_w  = max(2,  int(s * 0.026))
        draw.rectangle([0, 0, w - 1, h - 1], outline=c, width=out_w)
        x0, y0, x1, y1 = gap, gap, w - gap - 1, h - gap - 1
        draw.rectangle([x0, y0, x1, y1], fill=None, outline=c, width=in_w)
        pad = in_w + 5
        return x0 + pad, y0 + pad, x1 - pad, y1 - pad

    elif shape in ('circle', 'oval'):
        out_w = max(6, int(s * 0.08))
        draw.ellipse([0, 0, w - 1, h - 1], outline=c, width=out_w)
        m = out_w // 2 + 1
        cx, cy = w // 2, h // 2
        rx = int((w // 2 - m) * 0.68)
        ry = int((h // 2 - m) * 0.68)
        return cx - rx, cy - ry, cx + rx, cy + ry

    elif shape == 'double_circle':
        out_w = max(6, int(s * 0.076))
        gap   = max(10, int(s * 0.118))
        in_w  = max(2,  int(s * 0.024))
        draw.ellipse([0, 0, w - 1, h - 1], outline=c, width=out_w)
        m = out_w // 2 + 1
        x0, y0, x1, y1 = gap, gap, w - gap - 1, h - gap - 1
        draw.ellipse([x0, y0, x1, y1], outline=c, width=in_w)
        cx, cy = w // 2, h // 2
        irx = int(((x1 - x0) / 2 - in_w) * 0.70)
        iry = int(((y1 - y0) / 2 - in_w) * 0.70)
        return cx - irx, cy - iry, cx + irx, cy + iry

    elif shape in ('hexagon', 'diamond'):
        import math
        T = (255, 255, 255, 0)   # transparent cut
        cx, cy = w / 2, h / 2
        r_out = min(w, h) / 2 - 2
        out_w = max(8, int(s * 0.088))
        gap   = max(10, int(s * 0.108))
        in_w  = max(2,  int(s * 0.026))

        n_sides  = 6  if shape == 'hexagon' else 4
        start_a  = -math.pi / 2 if shape == 'hexagon' else -math.pi / 4

        def _poly(r):
            return [(cx + r * math.cos(start_a + i * 2 * math.pi / n_sides),
                     cy + r * math.sin(start_a + i * 2 * math.pi / n_sides))
                    for i in range(n_sides)]

        # 외곽 테두리 (ring 효과: 외곽 색 채움 → 안쪽 투명으로 컷)
        draw.polygon(_poly(r_out),          fill=c)
        draw.polygon(_poly(r_out - out_w),  fill=T)
        # 내부 테두리
        r_in  = r_out - out_w - gap
        r_in2 = r_in  - in_w
        draw.polygon(_poly(r_in),  fill=c)
        draw.polygon(_poly(r_in2), fill=T)

        # 텍스트 영역: 내접 원의 70%
        if shape == 'hexagon':
            ta = int(r_in2 * 0.80)   # 육각형 내접원 * 0.80
        else:
            ta = int(r_in2 * 0.68)   # 마름모 내접원 * 0.68
        return int(cx - ta), int(cy - ta), int(cx + ta), int(cy + ta)

    elif shape == 'postage':
        T = (255, 255, 255, 0)   # transparent cut
        # 전체 사각형을 color로 채움
        draw.rectangle([0, 0, w - 1, h - 1], fill=c)
        # 가장자리 반원 천공 모양 (우표 perforated edge)
        n_h  = max(5, round(w / (s * 0.17)))
        n_v  = max(4, round(h / (s * 0.17)))
        hr   = max(5, int(s * 0.058))   # 천공 반경
        for i in range(n_h + 1):
            x = round(i * w / n_h)
            draw.ellipse([x - hr, -hr, x + hr, hr],       fill=T)
            draw.ellipse([x - hr, h - hr, x + hr, h + hr], fill=T)
        for i in range(n_v + 1):
            y = round(i * h / n_v)
            draw.ellipse([-hr, y - hr, hr, y + hr],       fill=T)
            draw.ellipse([w - hr, y - hr, w + hr, y + hr], fill=T)
        # 내부 투명 영역
        brd = hr + 4
        draw.rectangle([brd, brd, w - brd - 1, h - brd - 1], fill=T)
        # 내부 얇은 테두리
        in_w  = max(2, int(s * 0.026))
        gap_i = max(5, int(s * 0.055))
        ix0, iy0 = brd + gap_i, brd + gap_i
        ix1, iy1 = w - brd - gap_i, h - brd - gap_i
        draw.rectangle([ix0, iy0, ix1, iy1], outline=c, width=in_w)
        return ix0 + in_w + 4, iy0 + in_w + 4, ix1 - in_w - 4, iy1 - in_w - 4

    elif shape == 'star_circle':
        import math
        T = (255, 255, 255, 0)   # transparent cut
        cx, cy = w / 2, h / 2
        r_out = min(w, h) / 2 - 2
        out_w = max(6, int(s * 0.078))
        gap   = max(10, int(s * 0.115))
        in_w  = max(2,  int(s * 0.024))
        n_teeth = 28
        r_peak  = r_out
        r_trough = r_out * 0.875

        # 기어/별 톱니 모양 외곽
        pts = []
        for i in range(n_teeth * 2):
            angle = i * math.pi / n_teeth
            r = r_peak if i % 2 == 0 else r_trough
            pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        draw.polygon(pts, fill=c)

        # 내부 투명 원 (컷아웃)
        r_clear = r_trough - out_w
        draw.ellipse([cx - r_clear, cy - r_clear, cx + r_clear, cy + r_clear], fill=T)

        # 내부 동심원 테두리
        r_ino = r_clear - gap
        r_ini = r_ino - in_w
        draw.ellipse([cx - r_ino, cy - r_ino, cx + r_ino, cy + r_ino], outline=c, width=in_w)
        draw.ellipse([cx - r_ini, cy - r_ini, cx + r_ini, cy + r_ini], fill=T)

        ta = int(r_ini * 0.72)
        return int(cx - ta), int(cy - ta), int(cx + ta), int(cy + ta)

    elif shape == 'badge':
        import math
        T = (255, 255, 255, 0)   # transparent cut
        cx, cy = w / 2, h / 2
        r_out = min(w, h) / 2 - 2
        out_w = max(6, int(s * 0.075))
        gap   = max(8, int(s * 0.095))
        in_w  = max(2, int(s * 0.024))

        # 외곽 원
        draw.ellipse([0, 0, w - 1, h - 1], outline=c, width=out_w)

        # 별/점 링
        r_dots = (r_out - out_w) * 0.85
        n_dots = 18
        dr = max(3, int(r_out * 0.042))
        for i in range(n_dots):
            angle = i * 2 * math.pi / n_dots
            sx = cx + r_dots * math.cos(angle)
            sy = cy + r_dots * math.sin(angle)
            draw.ellipse([sx - dr, sy - dr, sx + dr, sy + dr], fill=c)

        # 내부 원 (점 링 안쪽)
        r_in = r_dots - dr - gap
        draw.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], outline=c, width=in_w)

        # 중앙 가로 밴드 (텍스트 영역)
        bh   = r_in * 0.58
        bx0  = cx - r_in * 0.93
        bx1  = cx + r_in * 0.93
        by0  = cy - bh
        by1  = cy + bh
        draw.rectangle([bx0, by0, bx1, by1], fill=c)

        return int(bx0 + 5), int(by0 + 5), int(bx1 - 5), int(by1 - 5)

    return 0, 0, w, h


def _pick_stamp_font(text: str = '', *, framed: bool = True, preferred_family: str | None = None) -> str | None:
    text = text or ''
    preferred_path = _resolve_windows_font_path(preferred_family or '')
    if preferred_path:
        return preferred_path
    has_hangul = any('가' <= ch <= '힣' for ch in text)
    if framed:
        if has_hangul:
            candidates = [
                'C:/Windows/Fonts/malgunbd.ttf',
                'C:/Windows/Fonts/malgun.ttf',
                'C:/Windows/Fonts/arialuni.ttf',
                'C:/Windows/Fonts/arialbd.ttf',
            ]
        else:
            candidates = [
                'C:/Windows/Fonts/georgiab.ttf',
                'C:/Windows/Fonts/timesbd.ttf',
                'C:/Windows/Fonts/arialbd.ttf',
                'C:/Windows/Fonts/malgunbd.ttf',
            ]
    else:
        candidates = [
            'C:/Windows/Fonts/seguisym.ttf',
            'C:/Windows/Fonts/malgun.ttf',
            'C:/Windows/Fonts/cambria.ttc',
            'C:/Windows/Fonts/arial.ttf',
            'C:/Windows/Fonts/malgunbd.ttf',
        ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _build_stamp_image(text: str, width: int, height: int, outer_color: str, inner_color: str,
                       *, framed: bool = True, uppercase: bool = True,
                       preferred_family: str | None = None, preferred_size: int | None = None,
                       shape: str = 'rect') -> str:
    os.makedirs(_STAMP_CACHE_DIR, exist_ok=True)
    key = hashlib.sha1(
        f'v3|{text}|{width}|{height}|{outer_color}|{inner_color}|{int(framed)}'
        f'|{int(uppercase)}|{preferred_family or ""}|{preferred_size or 0}|{shape}'
        .encode('utf-8')
    ).hexdigest()[:16]
    out_path = os.path.join(_STAMP_CACHE_DIR, f'stamp_{key}.png')
    if os.path.exists(out_path):
        return out_path

    from PIL import Image, ImageDraw, ImageFont

    scale = 3
    _SQUARE_SHAPES = ('square', 'double_square', 'circle', 'double_circle',
                      'hexagon', 'diamond', 'star_circle', 'badge')
    # 정방형 도장은 폭=높이로 통일
    if shape in _SQUARE_SHAPES:
        side = max(width, height)
        width = height = side

    min_w = 180 if framed else 48
    min_h = 56  if framed else 36
    if shape in _SQUARE_SHAPES:
        side = max(max(width, height), min_w, min_h)
        w = h = side * scale
    else:
        w = max(min_w, int(width))  * scale
        h = max(min_h, int(height)) * scale

    img  = Image.new('RGBA', (w, h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # ── 프레임 그리기 ─────────────────────────────────────────────
    if framed:
        tx0, ty0, tx1, ty1 = _draw_seal_frame(draw, w, h, outer_color, shape)
    else:
        pad = max(6, int(min(w, h) * 0.08))
        tx0, ty0, tx1, ty1 = pad, pad, w - pad, h - pad

    ta_w = tx1 - tx0
    ta_h = ty1 - ty0

    # ── 텍스트 렌더링 ────────────────────────────────────────────
    font_path  = _pick_stamp_font(text, framed=framed, preferred_family=preferred_family)
    raw_label  = (text or '').strip()
    label      = raw_label.upper() if uppercase else raw_label
    lines      = label.split('\n') if '\n' in label else [label]

    if preferred_size:
        font_size = max(8, int(preferred_size * scale))
    else:
        base_ratio = 0.52 if framed else 0.68
        if len(lines) > 1:
            base_ratio *= 0.75
        font_size = max(8, int(ta_h * base_ratio))

    font = (ImageFont.truetype(font_path, font_size)
            if font_path else ImageFont.load_default())

    # 폰트 크기를 텍스트 영역에 맞게 조정
    for _ in range(40):
        bboxes   = [draw.textbbox((0, 0), ln, font=font) for ln in lines]
        max_tw   = max((b[2] - b[0]) for b in bboxes) if bboxes else 0
        line_h   = max((b[3] - b[1]) for b in bboxes) if bboxes else 0
        gap_h    = int(font_size * 0.18)
        total_th = line_h * len(lines) + gap_h * (len(lines) - 1)
        if (max_tw <= ta_w - 10 and total_th <= ta_h - 8) or font_size <= 18:
            break
        font_size -= max(2, int(font_size * 0.07))
        font = (ImageFont.truetype(font_path, font_size)
                if font_path else ImageFont.load_default())

    # 각 줄을 텍스트 영역 중앙에 배치
    shadow_off = max(2, int(min(w, h) * 0.025))
    cy_start   = ty0 + (ta_h - total_th) // 2
    c_rgba     = _color_hex_to_rgba(outer_color)
    shadow_col = (0, 0, 0, 65)

    for i, (line, bbox) in enumerate(zip(lines, bboxes)):
        lw = bbox[2] - bbox[0]
        lh = bbox[3] - bbox[1]
        x  = tx0 + (ta_w - lw) / 2 - bbox[0]
        y  = cy_start + i * (lh + gap_h) - bbox[1]
        draw.text((x + shadow_off, y + shadow_off), line, font=font, fill=shadow_col)
        draw.text((x, y), line, font=font, fill=c_rgba)

    img.save(out_path)
    return out_path



class StampSettingsDialog:
    """스탬프 색상/투명도 설정 다이얼로그."""
    def __new__(cls, tool, parent=None):
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                        QFormLayout, QSlider, QSpinBox,
                                        QCheckBox, QPushButton, QDialogButtonBox,
                                        QLabel)
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtGui import QColor

        dlg = QDialog(parent)
        dlg.setWindowTitle('스탬프 색상 / 투명도')
        dlg.setFixedWidth(300)
        layout = QVBoxLayout(dlg)

        # ── 투명도 ──────────────────────────────────────
        form = QFormLayout()
        h = QHBoxLayout()
        slider = QSlider(_Qt.Orientation.Horizontal)
        slider.setRange(10, 100)
        slider.setValue(int(tool._stamp_opacity * 100))
        spin = QSpinBox()
        spin.setRange(10, 100)
        spin.setSuffix(' %')
        spin.setValue(slider.value())
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        h.addWidget(slider)
        h.addWidget(spin)
        form.addRow('투명도:', h)
        layout.addLayout(form)
        layout.addSpacing(10)

        # ── 색상 덮어쓰기 ────────────────────────────────
        color_check = QCheckBox('색상 덮어쓰기  (캐릭터 · 심볼 · 기존 스탬프)')
        color_check.setChecked(tool._stamp_color_override is not None)
        layout.addWidget(color_check)

        cur_color = [tool._stamp_color_override or '#cc1111']
        color_btn = QPushButton()
        color_btn.setFixedHeight(30)

        def _refresh_btn():
            color_btn.setStyleSheet(
                f'background:{cur_color[0]}; border:1px solid #888; border-radius:4px;')
            color_btn.setText(cur_color[0])

        def _pick_color():
            from PySide6.QtWidgets import QColorDialog
            col = QColorDialog.getColor(QColor(cur_color[0]), dlg)
            if col.isValid():
                cur_color[0] = col.name()
                _refresh_btn()

        _refresh_btn()
        color_btn.clicked.connect(_pick_color)
        color_check.toggled.connect(color_btn.setEnabled)
        color_btn.setEnabled(color_check.isChecked())
        layout.addWidget(color_btn)

        layout.addSpacing(6)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        dlg._get_opacity = lambda: spin.value() / 100.0
        dlg._get_color   = lambda: cur_color[0] if color_check.isChecked() else None
        return dlg


class StampTool(BaseTool):
    name     = 'stamp'
    label    = '스탬프'
    cursor   = Qt.CursorShape.PointingHandCursor
    shortcut = 'P'

    def __init__(self):
        self.stamp_name           = 'Draft'
        self._circle_mode         = False
        self._circle_counter      = 1
        self._circle_color        = (0.8, 0.0, 0.0)
        self._circle_radius       = 10
        self._stamp_opacity       = 1.0
        self._stamp_color_override: str | None = None

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def _add_pending(self, pa: PendingAnnotation, view):
        view.pending_layer().add(pa)
        view.doc().mark_dirty()
        view.notify_pending_changed()

    def _preview_rect(self, fitz_rect, view, label: str = '', pen_color='#cc3300', brush_color=QColor(255, 220, 220, 140)):
        from PySide6.QtWidgets import QGraphicsItemGroup, QGraphicsRectItem, QGraphicsTextItem
        zoom = view.zoom()
        offset = view._page_offsets.get(view.current_page(), QPointF(0, 0))
        ox, oy = offset.x(), offset.y()
        x = fitz_rect.x0 * zoom + ox
        y = fitz_rect.y0 * zoom + oy
        w = fitz_rect.width * zoom
        h = fitz_rect.height * zoom
        group = QGraphicsItemGroup()
        item = QGraphicsRectItem(x, y, w, h)
        item.setPen(QPen(QColor(pen_color), 2.0))
        item.setBrush(QBrush(brush_color))
        group.addToGroup(item)
        if label:
            txt = QGraphicsTextItem(label)
            font = QFont('Malgun Gothic')
            font.setBold(True)
            font.setPixelSize(max(9, int(min(h * 0.45, 18 * zoom))))
            txt.setFont(font)
            txt.setDefaultTextColor(QColor(pen_color))
            txt.setTextWidth(max(1, w - 8))
            text_option = txt.document().defaultTextOption()
            text_option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            txt.document().setDefaultTextOption(text_option)
            txt.setPos(x + 4, y + max(0, (h - txt.boundingRect().height()) / 2 - 2))
            group.addToGroup(txt)
        group.setZValue(20)
        view.scene().addItem(group)
        return group

    def _place_builtin_stamp(self, pos, view):
        if self.stamp_name not in STAMP_NAMES:
            return
        label = format_stamp_label(self.stamp_name).upper()
        outer_color, _ = _stamp_style(label)
        self._place_generated_image_stamp(
            pos,
            view,
            label,
            width=147,
            height=48,
            color=outer_color,
        )

    def _place_custom_image(self, pos, custom, view):
        page_idx, fitz_pt = resolve_page_and_fitz_pt(view, pos)
        rect = fitz.Rect(fitz_pt.x - 60, fitz_pt.y - 60,
                         fitz_pt.x + 60, fitz_pt.y + 60)
        pa = PendingAnnotation(
            uid=view.pending_layer().next_uid(),
            page_index=page_idx,
            tool_name=self.name,
            annot_type='image',
            fitz_rect=rect,
            image_path=custom.get('path', ''),
            opacity=self._stamp_opacity,
        )
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QGraphicsPixmapItem
        q_item = None
        pxm = QPixmap(pa.image_path)
        if not pxm.isNull():
            pxm = pxm.scaled(
                max(1, int(rect.width * view.zoom())),
                max(1, int(rect.height * view.zoom())),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            offset = view.page_offset(page_idx)
            q_item = QGraphicsPixmapItem(pxm)
            q_item.setPos(rect.x0 * view.zoom() + offset.x(),
                          rect.y0 * view.zoom() + offset.y())
            q_item.setZValue(20)
            if self._stamp_opacity < 0.99:
                q_item.setOpacity(self._stamp_opacity)
            view.scene().addItem(q_item)
        pa.q_item = q_item
        self._add_pending(pa, view)

    def _place_generated_image_stamp(self, pos, view, text: str, *, width=147, height=48,
                                     color: str | None = None, framed: bool = True,
                                     uppercase: bool = True, font_family: str | None = None,
                                     font_size: int | None = None, shape: str = 'rect'):
        label = (text or '').strip()
        if not label:
            return
        # 정방형 도장은 폭=높이 통일
        if shape in ('square', 'double_square', 'circle', 'double_circle'):
            side = max(width, height)
            width = height = side
        outer_color, inner_color = _stamp_style(label)
        if color is not None:
            outer_color = color
        if self._stamp_color_override is not None:
            outer_color = self._stamp_color_override
        image_path = _build_stamp_image(label, width, height, outer_color, inner_color,
                                        framed=framed, uppercase=uppercase,
                                        preferred_family=font_family, preferred_size=font_size,
                                        shape=shape)
        page_idx, fitz_pt = resolve_page_and_fitz_pt(view, pos)
        rect = fitz.Rect(
            fitz_pt.x - width / 2,
            fitz_pt.y - height / 2,
            fitz_pt.x + width / 2,
            fitz_pt.y + height / 2,
        )
        pa = PendingAnnotation(
            uid=view.pending_layer().next_uid(),
            page_index=page_idx,
            tool_name=self.name,
            annot_type='image',
            fitz_rect=rect,
            image_path=image_path,
            opacity=self._stamp_opacity,
        )
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QGraphicsPixmapItem
        q_item = None
        pxm = QPixmap(image_path)
        if not pxm.isNull():
            pxm = pxm.scaled(
                max(1, int(rect.width * view.zoom())),
                max(1, int(rect.height * view.zoom())),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            offset = view.page_offset(page_idx)
            q_item = QGraphicsPixmapItem(pxm)
            q_item.setPos(rect.x0 * view.zoom() + offset.x(),
                          rect.y0 * view.zoom() + offset.y())
            q_item.setZValue(20)
            if self._stamp_opacity < 0.99:
                q_item.setOpacity(self._stamp_opacity)
            view.scene().addItem(q_item)
        pa.q_item = q_item
        self._add_pending(pa, view)

    def _place_text_stamp(self, pos, view, text: str, *, color=(0.7, 0.0, 0.0),
                          half_width=80, half_height=20, font_size=18,
                          pen_color='#cc3300', brush_color=QColor(255, 220, 220, 120),
                          font_family: str | None = None, shape: str = 'rect'):
        del pen_color, brush_color
        rgb = tuple(max(0, min(255, int(v * 255))) for v in color)
        outer_color = '#%02x%02x%02x' % rgb
        self._place_generated_image_stamp(
            pos, view, text,
            width=max(180, int(half_width * 2 + 60)),
            height=max(56, int(half_height * 2 + 24)),
            color=outer_color,
            font_family=font_family,
            font_size=font_size,
            shape=shape,
        )

    def _place_custom_text(self, pos, custom, view):
        text      = custom.get('text', '')
        font_size = int(custom.get('font_size', 18) or 18)
        shape     = custom.get('shape', 'rect')

        _sq = ('square', 'double_square', 'circle', 'double_circle',
               'hexagon', 'diamond', 'star_circle', 'badge')
        if shape in _sq:
            # 정방형 도장: 정사각 크기
            char_count = max(len(text.replace('\n', '')), 2)
            side = max(80, int(char_count * font_size * 1.0) + 30)
            half_width = half_height = side // 2
        elif shape == 'oval':
            width = max(160, int(max(len(text), 2) * font_size * 1.2) + 30)
            half_width  = max(70, width // 2)
            half_height = max(30, int(font_size * 0.7))
        else:
            width      = max(180, int(max(len(text), 2) * font_size * 1.35) + 40)
            half_width  = max(80, width // 2 - 30)
            half_height = max(20, int(font_size * 0.9))

        self._place_text_stamp(
            pos, view, text,
            color=tuple(custom.get('color', [0.7, 0.0, 0.0])),
            half_width=half_width, half_height=half_height,
            font_size=font_size,
            font_family=custom.get('font_family'),
            shape=shape,
        )

    def _place_character_stamp(self, pos, view, char_info: dict):
        image_path = char_info.get('image_path', '')
        if not image_path or not os.path.exists(image_path):
            return
        image_path = _prepare_transparent_stamp_png(image_path)
        page_idx, fitz_pt = resolve_page_and_fitz_pt(view, pos)
        half = 50
        rect = fitz.Rect(fitz_pt.x - half, fitz_pt.y - half,
                         fitz_pt.x + half, fitz_pt.y + half)
        pa = PendingAnnotation(
            uid=view.pending_layer().next_uid(),
            page_index=page_idx,
            tool_name=self.name,
            annot_type='image',
            fitz_rect=rect,
            image_path=image_path,
            opacity=self._stamp_opacity,
        )
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QGraphicsPixmapItem
        q_item = None
        pxm = QPixmap(image_path)
        if not pxm.isNull():
            pxm = pxm.scaled(
                max(1, int(rect.width * view.zoom())),
                max(1, int(rect.height * view.zoom())),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            offset = view.page_offset(page_idx)
            q_item = QGraphicsPixmapItem(pxm)
            q_item.setPos(rect.x0 * view.zoom() + offset.x(),
                          rect.y0 * view.zoom() + offset.y())
            q_item.setZValue(20)
            if self._stamp_opacity < 0.99:
                q_item.setOpacity(self._stamp_opacity)
            view.scene().addItem(q_item)
        pa.q_item = q_item
        self._add_pending(pa, view)

    def _place_date_stamp(self, pos, view):
        self._place_generated_image_stamp(
            pos,
            view,
            datetime.now().strftime('%Y-%m-%d'),
            width=128,
            height=28,
            color='#bf0000',
            framed=False,
            uppercase=False,
        )

    def _place_symbol_stamp(self, pos, view, symbol_info):
        self._place_generated_image_stamp(
            pos,
            view,
            symbol_info.get('text', ''),
            width=34,
            height=34,
            color='#bf0000',
            framed=False,
            uppercase=False,
        )

    def on_press(self, pos, event, view):
        return

    def on_move(self, pos, event, view):
        return

    def on_release(self, pos, event, view):
        if event.button() != Qt.MouseButton.LeftButton or not view.doc().is_open:
            return

        if self._circle_mode:
            self._place_circle_number(pos, view)
            return

        if self.stamp_name == DATE_STAMP_NAME:
            self._place_date_stamp(pos, view)
            return

        symbol_info = SYMBOL_STAMP_MAP.get(self.stamp_name)
        if symbol_info is not None:
            self._place_symbol_stamp(pos, view, symbol_info)
            return

        char_info = CHARACTER_STAMP_MAP.get(self.stamp_name)
        if char_info is not None:
            self._place_character_stamp(pos, view, char_info)
            return

        customs = load_custom_stamps()
        custom = next((c for c in customs if c.get('name') == self.stamp_name), None)
        if custom is not None:
            if custom.get('type') == 'image':
                self._place_custom_image(pos, custom, view)
            else:
                self._place_custom_text(pos, custom, view)
            return

        if self.stamp_name in STAMP_KR:
            self.stamp_name = STAMP_KR[self.stamp_name]
        self._place_builtin_stamp(pos, view)

    def _place_circle_number(self, pos, view):
        n   = self._circle_counter
        r   = self._circle_radius
        col = self._circle_color

        page_idx, fitz_pt = resolve_page_and_fitz_pt(view, pos)
        cx, cy  = fitz_pt.x, fitz_pt.y
        rect    = fitz.Rect(cx - r, cy - r, cx + r, cy + r)

        fs  = 13 if n < 10 else 11
        pad = fs * 0.25
        text_rect = fitz.Rect(cx - r, cy - r - pad, cx + r, cy + r - pad)

        pa_circle = PendingAnnotation(
            uid          = view.pending_layer().next_uid(),
            page_index   = page_idx,
            tool_name    = self.name,
            annot_type   = 'circle',
            fitz_rect    = rect,
            stroke_color = col,
            fill_color   = (1.0, 1.0, 1.0),
            border_width = 1.5,
        )
        pa_text = PendingAnnotation(
            uid          = view.pending_layer().next_uid(),
            page_index   = page_idx,
            tool_name    = self.name,
            annot_type   = 'direct_text',
            fitz_rect    = text_rect,
            text         = str(n),
            fontsize     = fs,
            fontname     = 'helv',
            text_color   = col,
            text_align   = fitz.TEXT_ALIGN_CENTER,
        )
        view.pending_layer().add(pa_circle)
        view.pending_layer().add(pa_text)
        view.doc().mark_dirty()
        self._circle_counter += 1

        zoom   = view.zoom()
        offset = view.page_offset(page_idx)
        ox, oy = offset.x(), offset.y()
        qcol   = QColor(int(col[0]*255), int(col[1]*255), int(col[2]*255))

        ei = QGraphicsEllipseItem(rect.x0*zoom+ox, rect.y0*zoom+oy,
                                  rect.width*zoom,  rect.height*zoom)
        ei.setPen(QPen(qcol, 1.5))
        ei.setBrush(QBrush(QColor(255, 255, 255)))
        ei.setZValue(20)
        view.scene().addItem(ei)
        pa_circle.q_item = ei

        ti = QGraphicsSimpleTextItem(str(n))
        tf = QFont('Helvetica', max(6, int(fs * zoom * 0.75)))
        ti.setFont(tf)
        ti.setBrush(qcol)
        br = ti.boundingRect()
        ti.setPos(
            (rect.x0 + rect.width  / 2) * zoom + ox - br.width()  / 2,
            (rect.y0 + rect.height / 2) * zoom + oy - br.height() / 2,
        )
        ti.setZValue(21)
        view.scene().addItem(ti)
        pa_text.q_item = ti

        view.notify_pending_changed()

    def on_key(self, event, view) -> bool:
        if event.key() == Qt.Key.Key_Escape and self._circle_mode:
            self.exit_circle_mode()
            return True
        return False

    def on_context_menu(self, pos, global_pos, view) -> bool:
        from PySide6.QtWidgets import QMenu

        ctx_page_idx, fitz_pt = resolve_page_and_fitz_pt(view, pos)
        page    = view.doc().fitz_page(ctx_page_idx) if view.doc().is_open else None

        hit_rect = None
        if page is not None:
            tol = self._circle_radius + 4
            for annot in list(page.annots()):
                try:
                    r = annot.rect
                except Exception:
                    continue
                if (r.x0 - tol <= fitz_pt.x <= r.x1 + tol and
                        r.y0 - tol <= fitz_pt.y <= r.y1 + tol):
                    hit_rect = annot.rect
                    break

        menu = QMenu(view)

        if hit_rect is not None:
            def _delete():
                xrefs = [a.xref for a in list(page.annots())
                         if abs(a.rect.x0 - hit_rect.x0) < 1.0 and
                            abs(a.rect.y0 - hit_rect.y0) < 1.0 and
                            abs(a.rect.x1 - hit_rect.x1) < 1.0 and
                            abs(a.rect.y1 - hit_rect.y1) < 1.0]
                for xref in xrefs:
                    for a in list(page.annots()):
                        if a.xref == xref:
                            page.delete_annot(a)
                            break
                view.doc().mark_dirty()
                view.refresh_page()
            menu.addAction('🗑  삭제').triggered.connect(_delete)
            menu.addSeparator()

        if self._circle_mode:
            lbl = menu.addAction(
                f'① 원번호 모드 켜짐  (다음: {self._circle_counter}번)')
            lbl.setEnabled(False)
            menu.addAction('↺  1번부터 다시').triggered.connect(
                lambda: self.reset_circle_counter(1))
            act_set = menu.addAction('✎  시작 번호 지정…')
            def _set_start(checked=False):
                n, ok = QInputDialog.getInt(
                    view, '원번호 시작', '시작 번호:',
                    self._circle_counter, 1, 9999)
                if ok:
                    self.reset_circle_counter(n)
            act_set.triggered.connect(_set_start)
            menu.addSeparator()
            menu.addAction('✕  원번호 모드 끄기  (ESC)').triggered.connect(
                self.exit_circle_mode)
        else:
            menu.addAction('① 원번호 모드 켜기').triggered.connect(
                lambda: setattr(self, '_circle_mode', True))

        menu.exec(global_pos)
        return True

    def reset_circle_counter(self, start: int = 1):
        self._circle_counter = start

    def exit_circle_mode(self):
        self._circle_mode    = False
        self._circle_counter = 1

