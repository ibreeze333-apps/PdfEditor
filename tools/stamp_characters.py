from __future__ import annotations

import hashlib
import math
import os
import tempfile

_CACHE_DIR = os.path.join(tempfile.gettempdir(), 'pdf_editor_stamp_cache')


def _rgba(hex_str: str) -> tuple[int, int, int, int]:
    value = (hex_str or '#cc1111').lstrip('#')
    if len(value) != 6:
        value = 'cc1111'
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


def _font_candidates() -> list[str]:
    return [
        'C:/Windows/Fonts/malgunbd.ttf',
        'C:/Windows/Fonts/malgun.ttf',
        'C:/Windows/Fonts/NanumGothicBold.ttf',
        'C:/Windows/Fonts/NanumMyeongjoBold.ttf',
        'C:/Windows/Fonts/arialbd.ttf',
    ]


def _first_existing_font() -> str | None:
    for path in _font_candidates():
        if os.path.exists(path):
            return path
    return None


def _draw_center_text(draw, text: str, cx: float, cy: float, max_width: float, base_size: int, fill, *, shadow=True):
    from PIL import ImageFont

    font_path = _first_existing_font()
    size = max(16, int(base_size))
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
    for _ in range(24):
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width or size <= 18:
            break
        size -= 2
        font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tx = cx - (bbox[2] - bbox[0]) / 2 - bbox[0]
    ty = cy - (bbox[3] - bbox[1]) / 2 - bbox[1]
    if shadow:
        draw.text((tx + 2, ty + 2), text, font=font, fill=(0, 0, 0, 48))
    draw.text((tx, ty), text, font=font, fill=fill)


def _draw_arc_text(draw, text: str, cx: float, cy: float, radius: float, base_size: int, fill, *, start_deg: float, end_deg: float):
    from PIL import ImageFont

    chars = [ch for ch in text if ch.strip()]
    if not chars:
        return
    font_path = _first_existing_font()
    size = max(14, int(base_size))
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
    if len(chars) == 1:
        angles = [(start_deg + end_deg) * 0.5]
    else:
        step = (end_deg - start_deg) / (len(chars) - 1)
        angles = [start_deg + step * i for i in range(len(chars))]
    for ch, angle_deg in zip(chars, angles):
        bbox = draw.textbbox((0, 0), ch, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        angle = math.radians(angle_deg)
        x = cx + radius * math.cos(angle) - w / 2 - bbox[0]
        y = cy + radius * math.sin(angle) - h / 2 - bbox[1]
        draw.text((x + 1.5, y + 1.5), ch, font=font, fill=(0, 0, 0, 36))
        draw.text((x, y), ch, font=font, fill=fill)


def _draw_hamster(draw, cx: float, cy: float, radius: float, color, lw: int):
    cheek = radius * 0.90
    face_top = cy - radius * 0.45
    face_bottom = cy + radius * 0.70
    draw.rounded_rectangle(
        [cx - cheek, face_top, cx + cheek, face_bottom],
        radius=radius * 0.58,
        outline=color,
        width=lw,
    )
    ear_r = radius * 0.28
    for sign in (-1, 1):
        ex = cx + sign * radius * 0.64
        ey = cy - radius * 0.78
        draw.ellipse([ex - ear_r, ey - ear_r, ex + ear_r, ey + ear_r], outline=color, width=lw)
        inner = ear_r * 0.42
        draw.ellipse([ex - inner, ey - inner, ex + inner, ey + inner], outline=color, width=max(1, lw - 1))
    for offset in (-0.34, 0.0, 0.34):
        x = cx + radius * offset
        draw.line([x, cy - radius * 0.55, x, cy - radius * 0.28], fill=color, width=max(1, lw - 1))
    eye_r = radius * 0.07
    for sign in (-1, 1):
        ex = cx + sign * radius * 0.27
        ey = cy - radius * 0.05
        draw.ellipse([ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r], fill=color)
        blush_r = radius * 0.06
        by = cy + radius * 0.18
        bx = cx + sign * radius * 0.55
        draw.ellipse([bx - blush_r, by - blush_r, bx + blush_r, by + blush_r], fill=color)
    nose_r = radius * 0.06
    draw.ellipse([cx - nose_r, cy + radius * 0.10 - nose_r, cx + nose_r, cy + radius * 0.10 + nose_r], fill=color)
    draw.arc([cx - radius * 0.18, cy + radius * 0.14, cx, cy + radius * 0.40], 0, 180, fill=color, width=max(1, lw - 1))
    draw.arc([cx, cy + radius * 0.14, cx + radius * 0.18, cy + radius * 0.40], 0, 180, fill=color, width=max(1, lw - 1))


def _draw_rabbit(draw, cx: float, cy: float, radius: float, color, lw: int):
    ear_w = radius * 0.23
    ear_h = radius * 0.82
    top = cy - radius * 1.10
    for sign in (-1, 1):
        ex = cx + sign * radius * 0.30
        draw.rounded_rectangle(
            [ex - ear_w, top, ex + ear_w, top + ear_h * 2],
            radius=ear_w,
            outline=color,
            width=lw,
        )
        inner_w = ear_w * 0.42
        draw.rounded_rectangle(
            [ex - inner_w, top + radius * 0.14, ex + inner_w, top + ear_h * 1.42],
            radius=inner_w,
            outline=color,
            width=max(1, lw - 1),
        )
    face_w = radius * 0.88
    face_top = cy - radius * 0.48
    face_bottom = cy + radius * 0.74
    draw.rounded_rectangle(
        [cx - face_w, face_top, cx + face_w, face_bottom],
        radius=radius * 0.62,
        outline=color,
        width=lw,
    )
    eye_r = radius * 0.07
    for sign in (-1, 1):
        ex = cx + sign * radius * 0.27
        ey = cy - radius * 0.02
        draw.ellipse([ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r], fill=color)
        dot_r = radius * 0.05
        bx = cx + sign * radius * 0.55
        by = cy + radius * 0.15
        draw.ellipse([bx - dot_r, by - dot_r, bx + dot_r, by + dot_r], fill=color)
    nose_w = radius * 0.10
    draw.ellipse([cx - nose_w, cy + radius * 0.12 - nose_w * 0.7, cx + nose_w, cy + radius * 0.12 + nose_w * 0.7], fill=color)
    draw.line([cx, cy + radius * 0.16, cx, cy + radius * 0.30], fill=color, width=max(1, lw - 1))
    draw.arc([cx - radius * 0.22, cy + radius * 0.22, cx, cy + radius * 0.44], 0, 180, fill=color, width=max(1, lw - 1))
    draw.arc([cx, cy + radius * 0.22, cx + radius * 0.22, cy + radius * 0.44], 0, 180, fill=color, width=max(1, lw - 1))


def _draw_star(draw, cx: float, cy: float, radius: float, color):
    pts = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        rr = radius if i % 2 == 0 else radius * 0.42
        pts.append((cx + rr * math.cos(angle), cy + rr * math.sin(angle)))
    draw.polygon(pts, fill=color)


def _draw_kids(draw, cx: float, cy: float, radius: float, color, lw: int):
    face_r = radius * 0.34
    left_x = cx - radius * 0.40
    right_x = cx + radius * 0.38
    base_y = cy + radius * 0.02

    # left kid with cap
    draw.ellipse([left_x - face_r, base_y - face_r, left_x + face_r, base_y + face_r], outline=color, width=lw)
    draw.pieslice([left_x - face_r * 1.08, base_y - face_r * 1.30, left_x + face_r * 1.08, base_y - face_r * 0.02], 180, 360, fill=color)
    draw.polygon([
        (left_x - face_r * 0.08, base_y - face_r * 0.40),
        (left_x + face_r * 1.18, base_y - face_r * 0.58),
        (left_x + face_r * 1.18, base_y - face_r * 0.36),
        (left_x - face_r * 0.08, base_y - face_r * 0.18),
    ], fill=color)

    # right kid with hair buns
    draw.ellipse([right_x - face_r, base_y - face_r, right_x + face_r, base_y + face_r], outline=color, width=lw)
    bun_r = face_r * 0.28
    for sign in (-1, 1):
        bx = right_x + sign * face_r * 0.85
        by = base_y - face_r * 0.50
        draw.ellipse([bx - bun_r, by - bun_r, bx + bun_r, by + bun_r], fill=color)
    draw.arc([right_x - face_r * 0.90, base_y - face_r * 1.18, right_x + face_r * 0.90, base_y - face_r * 0.32], 200, 340, fill=color, width=max(1, lw + 1))

    eye_r = face_r * 0.08
    for fx in (left_x, right_x):
        for sign in (-1, 1):
            ex = fx + sign * face_r * 0.24
            ey = base_y - face_r * 0.08
            draw.ellipse([ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r], fill=color)
        draw.arc([fx - face_r * 0.20, base_y + face_r * 0.14, fx + face_r * 0.20, base_y + face_r * 0.34], 0, 180, fill=color, width=max(1, lw - 1))


def build_character_stamp(char_type: str, text: str, color_hex: str, stamp_size: int = 100) -> str:
    from PIL import Image, ImageDraw

    os.makedirs(_CACHE_DIR, exist_ok=True)
    key = hashlib.sha1(f'v3|{char_type}|{text}|{color_hex}|{stamp_size}'.encode('utf-8')).hexdigest()[:16]
    out = os.path.join(_CACHE_DIR, f'char_{key}.png')
    if os.path.exists(out):
        return out

    scale = 3
    size = int(stamp_size) * scale
    img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    color = _rgba(color_hex)
    cx = cy = size / 2
    ring_r = size * 0.45
    ring_lw = max(5, int(size * 0.020))
    draw.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r], outline=color, width=ring_lw)

    if char_type == 'hamster':
        _draw_hamster(draw, cx, cy - ring_r * 0.12, ring_r * 0.34, color, ring_lw)
        _draw_center_text(draw, text, cx, cy + ring_r * 0.58, ring_r * 1.42, size * 0.108, color)
    elif char_type == 'rabbit':
        _draw_rabbit(draw, cx, cy - ring_r * 0.08, ring_r * 0.32, color, ring_lw)
        _draw_center_text(draw, text, cx, cy + ring_r * 0.58, ring_r * 1.46, size * 0.106, color)
    elif char_type == 'kids':
        _draw_arc_text(draw, text, cx, cy, ring_r * 0.78, size * 0.080, color, start_deg=208, end_deg=332)
        _draw_kids(draw, cx, cy - ring_r * 0.02, ring_r * 0.56, color, ring_lw)
        star_y = cy + ring_r * 0.66
        for offset in (-0.34, -0.17, 0.0, 0.17, 0.34):
            _draw_star(draw, cx + ring_r * offset, star_y, ring_r * 0.060, color)
    else:
        _draw_center_text(draw, text, cx, cy, ring_r * 1.40, size * 0.110, color)

    img.save(out)
    return out
